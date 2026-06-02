#!/usr/bin/env python3
"""Backfill historical market price data from Kalshi.

Fetches all markets with MIN_HISTORY_DAYS+ days of history and stores
daily candlestick data in the market_prices table.
"""
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from sqlalchemy.dialects.postgresql import insert as pg_insert

from kalshi.client import KalshiClient
from db.models import Market, MarketPrice
from db.session import get_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MIN_HISTORY_DAYS = int(os.environ.get('MIN_HISTORY_DAYS', '365'))


def upsert_market(session, market):
    stmt = pg_insert(Market).values(
        ticker=market.ticker,
        title=market.title,
        category=market.category,
        status=market.status,
        close_date=market.close_time,
        created_at=market.open_time,
        series_ticker=market.series_ticker,
    ).on_conflict_do_update(
        index_elements=['ticker'],
        set_={
            'title': market.title,
            'category': market.category,
            'status': market.status,
            'close_date': market.close_time,
            'series_ticker': market.series_ticker,
        },
    )
    session.execute(stmt)


def upsert_prices(session, ticker: str, price_points) -> int:
    if not price_points:
        return 0
    rows = [
        {
            'ticker': ticker,
            'timestamp': pp.ts,
            'yes_bid': pp.yes_bid,
            'yes_ask': pp.yes_ask,
            'volume': pp.volume,
        }
        for pp in price_points
    ]
    stmt = pg_insert(MarketPrice).values(rows).on_conflict_do_nothing(
        index_elements=['ticker', 'timestamp']
    )
    session.execute(stmt)
    return len(rows)


def main():
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=MIN_HISTORY_DAYS)
    logger.info('Backfill starting (min_history_days=%d, cutoff=%s)', MIN_HISTORY_DAYS, cutoff.date())

    with KalshiClient() as client:
        logger.info('Fetching all markets from Kalshi...')
        all_markets = client.get_markets()
        logger.info('Fetched %d total markets', len(all_markets))

        qualifying = [m for m in all_markets if m.open_time and m.open_time <= cutoff]
        logger.info('%d markets qualify with %d+ days of history', len(qualifying), MIN_HISTORY_DAYS)

        session = get_session()
        try:
            for i, market in enumerate(qualifying, 1):
                logger.info(
                    '[%d/%d] %s — %s', i, len(qualifying), market.ticker, market.title[:60]
                )
                upsert_market(session, market)
                session.flush()

                start_ts = int(market.open_time.timestamp())
                end_ts = int(datetime.now(tz=timezone.utc).timestamp())
                prices = client.get_market_history(
                    market.ticker,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    period_interval=1440,
                )
                n = upsert_prices(session, market.ticker, prices)
                logger.info('  -> stored %d price points', n)
                session.commit()
                time.sleep(0.2)

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    logger.info('Backfill complete')


if __name__ == '__main__':
    main()
