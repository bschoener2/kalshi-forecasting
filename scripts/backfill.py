#!/usr/bin/env python3
"""Backfill historical candlestick data from Kalshi.

Iterates candidate series (from market_stats table) and back-fills any
missing daily candles for each representative market.
Run select_markets.py first to populate market_stats.
"""
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from kalshi.client import KalshiClient
from db.models import Market, MarketPrice, MarketStats
from db.session import get_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    logger.info('Backfill starting')
    session = get_session()
    try:
        # Get all markets that have stats (i.e. selected candidates)
        rows = session.execute(
            select(MarketStats.ticker, MarketStats.series_ticker)
        ).all()
        logger.info('Markets to backfill: %d', len(rows))

        with KalshiClient() as client:
            for ticker, series_ticker in rows:
                if not series_ticker:
                    logger.warning('%s: no series_ticker, skipping', ticker)
                    continue

                latest_ts = session.scalar(
                    select(func.max(MarketPrice.timestamp))
                    .where(MarketPrice.ticker == ticker)
                )
                start_ts = int(latest_ts.timestamp()) + 1 if latest_ts else None
                end_ts = int(datetime.now(tz=timezone.utc).timestamp())

                candles = client.get_market_candlesticks(
                    series_ticker=series_ticker,
                    market_ticker=ticker,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    period_interval=1440,
                )
                if candles:
                    rows_to_insert = [
                        {
                            'ticker': ticker,
                            'timestamp': c.ts,
                            'yes_bid': c.yes_bid,
                            'yes_ask': c.yes_ask,
                            'volume': c.volume,
                        }
                        for c in candles
                    ]
                    stmt = pg_insert(MarketPrice).values(rows_to_insert).on_conflict_do_nothing(
                        index_elements=['ticker', 'timestamp']
                    )
                    session.execute(stmt)
                    session.commit()
                    logger.info('%s: +%d candles', ticker, len(candles))
                else:
                    logger.debug('%s: no new candles', ticker)
                time.sleep(0.2)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info('Backfill complete')


if __name__ == '__main__':
    main()
