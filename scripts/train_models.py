#!/usr/bin/env python3
"""Phase 3: Forecasting Models.

For each candidate market (from market_stats, ordered by rank_score):
  1. Load daily mid-price series from market_prices.
  2. Run walk-forward CV for each of the 5 models.
  3. Compute MAE, RMSE, directional accuracy, EV, Sharpe.
  4. Apply Benjamini-Hochberg FDR correction across all model×market pairs.
  5. Persist results to model_results table.
  6. Print ranked leaderboard and write model_leaderboard.csv.

Usage:
  python scripts/train_models.py              # top 20 markets
  TOP_N=5 python scripts/train_models.py      # top 5 only (fast)
"""
import csv
import logging
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import ModelResult, MarketStats, MarketPrice
from db.session import get_session
from models import ALL_MODELS
from models.evaluator import WalkForwardEvaluator, apply_bh_correction

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings('ignore')

TOP_N = int(os.environ.get('TOP_N', '20'))
MIN_TRAIN = int(os.environ.get('MIN_TRAIN', '60'))
STEP = int(os.environ.get('STEP', '7'))
OUTPUT_CSV = os.environ.get('OUTPUT_CSV', 'model_leaderboard.csv')
TC_CENTS = float(os.environ.get('TC_CENTS', '2.0'))  # round-trip transaction cost

evaluator = WalkForwardEvaluator(min_train=MIN_TRAIN, step=STEP)


def load_price_series(session, ticker: str) -> np.ndarray:
    """Load mid-price series (in cents) from market_prices, sorted by timestamp."""
    rows = session.execute(
        select(MarketPrice.yes_bid, MarketPrice.yes_ask)
        .where(MarketPrice.ticker == ticker)
        .where(MarketPrice.yes_bid.isnot(None))
        .where(MarketPrice.yes_ask.isnot(None))
        .order_by(MarketPrice.timestamp)
    ).all()
    if not rows:
        return np.array([])
    return np.array([(r.yes_bid + r.yes_ask) / 2.0 for r in rows])


def upsert_result(session, res):
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
        set_={
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
        },
    )
    session.execute(stmt)


def main():
    logger.info('Phase 3: Forecasting Models')
    logger.info('TOP_N=%d  MIN_TRAIN=%d  STEP=%d  TC=%.1f¢', TOP_N, MIN_TRAIN, STEP, TC_CENTS)

    session = get_session()
    try:
        # Load top-N candidates by rank_score
        candidates = session.execute(
            select(MarketStats.ticker, MarketStats.num_candles, MarketStats.series_ticker)
            .order_by(MarketStats.rank_score.desc())
            .limit(TOP_N)
        ).all()
        logger.info('Running models on %d candidate markets', len(candidates))

        all_results = []

        for i, (ticker, num_candles, series_ticker) in enumerate(candidates, 1):
            y = load_price_series(session, ticker)
            if len(y) < MIN_TRAIN + 10:
                logger.info('[%d/%d] %s — too few points (%d), skip', i, len(candidates), ticker, len(y))
                continue

            logger.info('[%d/%d] %s  |  %d points', i, len(candidates), ticker, len(y))

            for ModelClass in ALL_MODELS:
                model = ModelClass()
                try:
                    result = evaluator.evaluate(ticker, y, model)
                    if result is None:
                        continue
                    logger.info(
                        '  %-8s  MAE=%.2f  RMSE=%.2f  DirAcc=%.1f%%  EV=%.3f¢  Sharpe=%.2f  p=%.3f',
                        model.name(),
                        result.mae, result.rmse,
                        result.dir_accuracy * 100,
                        result.ev_cents, result.sharpe, result.ev_pvalue,
                    )
                    all_results.append(result)
                except Exception as exc:
                    logger.warning('  %-8s  ERROR: %s', model.name(), exc)

        # Multiple-testing correction (Benjamini-Hochberg FDR)
        logger.info('\nApplying BH FDR correction across %d model×market results...', len(all_results))
        apply_bh_correction(all_results, fdr=0.05)

        # Persist to DB
        for res in all_results:
            upsert_result(session, res)
        session.commit()

        # Rank by Sharpe-adjusted EV (significant combos first, then rest)
        all_results.sort(key=lambda r: (-int(r.is_significant), -r.sharpe, -r.ev_cents))

        # Print leaderboard
        sig = [r for r in all_results if r.is_significant]
        logger.info('\n=== LEADERBOARD (top 30 by Sharpe, significant first) ===')
        for r in all_results[:30]:
            sig_marker = '*** ' if r.is_significant else '    '
            logger.info(
                '%s%-10s  %-45s  EV=%+.3f¢  Sharpe=%+.2f  DirAcc=%.0f%%  p=%.3f',
                sig_marker, r.model_name, r.ticker[:45],
                r.ev_cents, r.sharpe, r.dir_accuracy * 100, r.ev_pvalue,
            )

        logger.info(
            '\nSignificant combos (FDR 5%%): %d / %d total',
            len(sig), len(all_results),
        )

        # Write CSV
        if all_results:
            with open(OUTPUT_CSV, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'ticker', 'model', 'n_pred', 'mae', 'rmse',
                    'dir_acc_pct', 'ev_cents', 'sharpe',
                    'p_value', 'fdr_adj_p', 'significant',
                ])
                for r in all_results:
                    writer.writerow([
                        r.ticker, r.model_name, r.n_predictions,
                        round(r.mae, 4), round(r.rmse, 4),
                        round(r.dir_accuracy * 100, 1),
                        round(r.ev_cents, 4), round(r.sharpe, 4),
                        round(r.ev_pvalue, 6), round(r.ev_fdr_adjusted, 6),
                        r.is_significant,
                    ])
            logger.info('Wrote %d rows to %s', len(all_results), OUTPUT_CSV)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    main()
