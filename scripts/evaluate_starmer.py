#!/usr/bin/env python3
"""Focused evaluation of all 8 models on KXLEAVESTARMER-26JUL01.

This script runs the original 5 models plus Ridge, Time-to-Expiry, and
Prophet on a single market, passing date information to the date-aware
models. Results are printed and stored in model_results.
"""
import logging
import os
import sys
import warnings
from datetime import date, datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logging.getLogger('prophet').setLevel(logging.ERROR)
logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import MarketPrice, MarketStats, ModelResult
from db.session import get_session
from models.naive import NaiveModel
from models.arima import ARIMAModel
from models.ets import ETSModel
from models.xgboost_model import XGBoostModel
from models.lstm import LSTMModel
from models.ridge import RidgeModel
from models.tte_model import TimeToExpiryModel
from models.prophet_model import ProphetModel
from models.evaluator import walk_forward, compute_metrics, apply_bh_correction, EvalResult

TICKER = 'KXLEAVESTARMER-26JUL01'
EXPIRY_DATE = date(2026, 7, 1)
MIN_TRAIN = 60
STEP = 5          # slightly tighter step for single-market focus
TC_CENTS = 1.0


def load_series(session) -> tuple[np.ndarray, date]:
    """Return (mid_prices_array, data_start_date)."""
    rows = session.execute(
        select(MarketPrice.timestamp, MarketPrice.yes_bid, MarketPrice.yes_ask)
        .where(MarketPrice.ticker == TICKER)
        .where(MarketPrice.yes_bid.isnot(None))
        .where(MarketPrice.yes_ask.isnot(None))
        .order_by(MarketPrice.timestamp)
    ).all()
    if not rows:
        raise ValueError(f'No price data found for {TICKER}')
    y = np.array([(r.yes_bid + r.yes_ask) / 2.0 for r in rows])
    start_date = rows[0].timestamp.date()
    return y, start_date


def upsert_result(session, res: EvalResult):
    stmt = pg_insert(ModelResult).values(
        ticker=res.ticker,
        model_name=res.model_name,
        computed_at=datetime.now(tz=timezone.utc),
        n_predictions=res.n_predictions,
        mae=res.mae,
        rmse=res.rmse,
        dir_accuracy=res.dir_accuracy,
        ev_cents=res.ev_cents,
        ev_pvalue=res.ev_pvalue,
        ev_fdr_adjusted=res.ev_fdr_adjusted,
        sharpe=res.sharpe,
        is_significant=res.is_significant,
    ).on_conflict_do_update(
        index_elements=['ticker', 'model_name'],
        set_={k: v for k, v in {
            'computed_at': datetime.now(tz=timezone.utc),
            'n_predictions': res.n_predictions,
            'mae': res.mae,
            'rmse': res.rmse,
            'dir_accuracy': res.dir_accuracy,
            'ev_cents': res.ev_cents,
            'ev_pvalue': res.ev_pvalue,
            'ev_fdr_adjusted': res.ev_fdr_adjusted,
            'sharpe': res.sharpe,
            'is_significant': res.is_significant,
        }.items()},
    )
    session.execute(stmt)


def main():
    logger.info('Evaluating all 8 models on %s', TICKER)
    logger.info('Expiry: %s  MIN_TRAIN=%d  STEP=%d  TC=%.1f¢', EXPIRY_DATE, MIN_TRAIN, STEP, TC_CENTS)

    session = get_session()
    y, start_date = load_series(session)
    logger.info('Loaded %d data points  start=%s  expiry=%s', len(y), start_date, EXPIRY_DATE)
    logger.info('Price range: [%.1f, %.1f]  current: %.1f¢', y.min(), y.max(), y[-1])

    models = [
        NaiveModel(),
        ARIMAModel(),
        ETSModel(),
        XGBoostModel(),
        LSTMModel(),
        RidgeModel(),
        TimeToExpiryModel(expiry_date=EXPIRY_DATE, data_start_date=start_date),
        ProphetModel(data_start_date=start_date),
    ]

    results = []
    for model in models:
        logger.info('Running %s...', model.name())
        try:
            preds, actuals = walk_forward(y, model, min_train=MIN_TRAIN, step=STEP)
            if len(preds) < 5:
                logger.warning('  Too few predictions (%d), skip', len(preds))
                continue
            m = compute_metrics(preds, actuals, tc_cents=TC_CENTS)
            res = EvalResult(
                model_name=model.name(),
                ticker=TICKER,
                **m,
            )
            results.append(res)
            logger.info(
                '  %-8s  n=%d  MAE=%.2f  RMSE=%.2f  DirAcc=%.1f%%  EV=%+.3f¢  Sharpe=%+.2f  p=%.3f',
                model.name(), res.n_predictions,
                res.mae, res.rmse,
                res.dir_accuracy * 100,
                res.ev_cents, res.sharpe, res.ev_pvalue,
            )
        except Exception as exc:
            logger.warning('  %s FAILED: %s', model.name(), exc)

    # BH correction within this market's 8 models
    apply_bh_correction(results, fdr=0.05)

    # Persist
    for res in results:
        upsert_result(session, res)
    session.commit()
    session.close()

    # Print ranked summary
    results.sort(key=lambda r: -r.sharpe)
    print(f'\n{"="*70}')
    print(f'KXLEAVESTARMER-26JUL01 — Model Comparison (ranked by Sharpe)')
    print(f'{"="*70}')
    print(f'  {"Model":<10}  {"EV":>8}  {"Sharpe":>8}  {"DirAcc":>8}  {"MAE":>7}  {"p-val":>7}  {"Sig?"}')
    print(f'  {"-"*10}  {"-"*8}  {"-"*8}  {"-"*8}  {"-"*7}  {"-"*7}  {"-"*5}')
    for r in results:
        sig = '  ***' if r.is_significant else ''
        print(
            f'  {r.model_name:<10}  {r.ev_cents:>+7.3f}¢  {r.sharpe:>+8.2f}  '
            f'{r.dir_accuracy*100:>7.1f}%  {r.mae:>7.2f}  {r.ev_pvalue:>7.3f}{sig}'
        )
    print(f'{"="*70}')
    sig_count = sum(r.is_significant for r in results)
    print(f'Significant at FDR 5%: {sig_count}/{len(results)}')


if __name__ == '__main__':
    main()
