#!/usr/bin/env python3
"""Incremental sync: fetch latest daily prices for all active markets in DB."""
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
from db.models import Market, MarketPrice
from db.session import get_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main():
    logger.info('Incremental sync starting')
    session = get_session()
    try:
        markets = session.scalars(
            select(Market).where(Market.status.in_(['open', 'active']))
        ).all()
        logger.info('Syncing %d active markets', len(markets))

        with KalshiClient() as client:
            for market in markets:
                latest_ts = session.scalar(
                    select(func.max(MarketPrice.timestamp))
                    .where(MarketPrice.ticker == market.ticker)
                )
                start_ts = int(latest_ts.timestamp()) + 1 if latest_ts else None
                end_ts = int(datetime.now(tz=timezone.utc).timestamp())

                prices = client.get_market_history(
                    market.ticker,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    period_interval=1440,
                )
                if prices:
                    rows = [
                        {
                            'ticker': market.ticker,
                            'timestamp': pp.ts,
                            'yes_bid': pp.yes_bid,
                            'yes_ask': pp.yes_ask,
                            'volume': pp.volume,
                        }
                        for pp in prices
                    ]
                    stmt = pg_insert(MarketPrice).values(rows).on_conflict_do_nothing(
                        index_elements=['ticker', 'timestamp']
                    )
                    session.execute(stmt)
                    session.commit()
                    logger.info('%s: +%d prices', market.ticker, len(prices))
                time.sleep(0.1)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info('Sync complete')


if __name__ == '__main__':
    main()
