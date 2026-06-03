#!/usr/bin/env python3
"""Noon Runner — daily APScheduler job for KXLEAVESTARMER.

Runs at 12:00 PST every weekday:
  1. Fetch latest market price from Kalshi
  2. Run ARIMA + ETS ensemble forecast
  3. Compute fractional Kelly position size
  4. Write PENDING_APPROVAL row to daily_decisions
  5. Print summary for human review (approval handled by web UI)

Usage:
  python scripts/noon_runner.py              # start scheduler (blocking)
  python scripts/noon_runner.py --once       # run immediately once, then exit
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import numpy as np
from sqlalchemy import select

from db.models import MarketPrice, DailyDecision
from db.session import get_session
from kalshi.client import KalshiClient
from runner.forecaster import generate_forecast, TICKER
from runner.position_sizer import compute_position, BUDGET_DOLLARS

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def load_history(session) -> np.ndarray:
    rows = session.execute(
        select(MarketPrice.yes_bid, MarketPrice.yes_ask)
        .where(MarketPrice.ticker == TICKER)
        .where(MarketPrice.yes_bid.isnot(None))
        .order_by(MarketPrice.timestamp)
    ).all()
    return np.array([(r.yes_bid + r.yes_ask) / 2.0 for r in rows])


def already_decided_today(session) -> bool:
    today = date.today()
    existing = session.execute(
        select(DailyDecision.id)
        .where(DailyDecision.ticker == TICKER)
        .where(DailyDecision.date == today)
    ).first()
    return existing is not None


def run_noon_decision():
    logger.info('=== Noon Runner starting (%s) ===', datetime.now(tz=timezone.utc).isoformat())
    session = get_session()
    try:
        if already_decided_today(session):
            logger.info('Decision already exists for today — skipping.')
            return

        # Load price history from DB
        y = load_history(session)
        if len(y) == 0:
            logger.error('No price history in DB for %s', TICKER)
            return
        logger.info('Loaded %d price points, current=%.1f¢', len(y), y[-1])

        # Generate forecast
        forecast = generate_forecast(y, min_confidence=0.1)
        if forecast is None or forecast.direction == 'hold':
            logger.info('Forecast says hold — no trade today.')
            _write_hold(session, y[-1])
            return

        # Get available balance from Kalshi
        with KalshiClient() as client:
            balance = client.get_balance()
        available_cents = balance.available_balance_cents
        if available_cents <= 0:
            # Fallback: use configured budget
            available_cents = int(BUDGET_DOLLARS * 100)
            logger.warning('No balance from API, using configured budget: %d¢', available_cents)

        # Position sizing
        pos = compute_position(
            current_price_cents=forecast.current_price,
            direction=forecast.direction,
            confidence=forecast.confidence,
            available_budget_cents=available_cents,
        )

        if pos['n_contracts'] < 1:
            logger.info('Position size rounds to 0 contracts — no trade.')
            _write_hold(session, y[-1])
            return

        # Write PENDING_APPROVAL decision
        decision = DailyDecision(
            date=date.today(),
            ticker=TICKER,
            model='arima+ets',
            forecast=round(forecast.predicted_price, 2),
            recommended_action=forecast.direction,
            # Repurpose confidence to store n_contracts for order_executor
            confidence=pos['n_contracts'],
            status='pending',
        )
        session.add(decision)
        session.commit()

        logger.info(
            '>>> PENDING APPROVAL  decision_id=%d  action=%s  %d × %s @ %d¢  '
            'predicted=%.1f¢  confidence=%.2f',
            decision.id,
            forecast.direction,
            pos['n_contracts'],
            TICKER,
            pos['price_cents'],
            forecast.predicted_price,
            forecast.confidence,
        )
        logger.info('Approve at http://localhost:8000/decisions')

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _write_hold(session, current_price):
    decision = DailyDecision(
        date=date.today(),
        ticker=TICKER,
        model='arima+ets',
        forecast=round(float(current_price), 2),
        recommended_action='hold',
        confidence=0.0,
        status='hold',
    )
    session.add(decision)
    session.commit()
    logger.info('Hold decision written (decision_id=%d)', decision.id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Run once immediately then exit')
    args = parser.parse_args()

    if args.once:
        run_noon_decision()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler(timezone='US/Pacific')
    scheduler.add_job(run_noon_decision, 'cron', hour=12, minute=0,
                      day_of_week='mon-fri', id='noon_runner')
    logger.info('Scheduler started — noon runner fires Mon–Fri at 12:00 PST')
    logger.info('Run with --once to fire immediately')
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info('Scheduler stopped')


if __name__ == '__main__':
    main()
