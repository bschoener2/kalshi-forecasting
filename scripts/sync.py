#!/usr/bin/env python3
"""Incremental sync: fetch latest daily candles for all candidate markets."""
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
from db.models import MarketPrice, MarketStats
from db.session import get_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    logger.info('Incremental sync starting')
    session = get_session()
    try:
        rows = session.execute(
            select(MarketStats.ticker, MarketStats.series_ticker)
        ).all()
        logger.info('Syncing %d candidate markets', len(rows))

        with KalshiClient() as client:
            for ticker, series_ticker in rows:
                if not series_ticker:
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
                time.sleep(0.15)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info('Sync complete')


if __name__ == '__main__':
    main()
