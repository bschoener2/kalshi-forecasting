#!/usr/bin/env python3
"""Phase 2: Market Selection.

Discovers Kalshi series/markets suitable for time-series forecasting:
  1. Enumerate all series; keep those with recurring frequency and relevant category.
  2. For each candidate series find the market with the most historical candles.
  3. Fetch daily candlestick data and compute stats.
  4. Rank by a composite score: history depth × liquidity / spread.
  5. Write results to DB (market_stats) and a CSV report.

Endpoint notes:
  - /series                                         → list all series
  - /markets?series_ticker=X                        → markets in a series
  - /series/{s}/markets/{m}/candlesticks            → OHLC history (period_interval in minutes)
"""
import csv
import logging
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from sqlalchemy.dialects.postgresql import insert as pg_insert

from kalshi.client import KalshiClient
from db.models import Market, MarketPrice, MarketStats
from db.session import get_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

MIN_CANDLES = int(os.environ.get('MIN_CANDLES', '90'))    # ~3 months of daily data
OUTPUT_CSV = os.environ.get('OUTPUT_CSV', 'market_candidates.csv')

TARGET_CATEGORIES = {
    'Economics', 'Financials', 'Crypto', 'Politics',
    'Climate and Weather', 'Companies', 'Commodities',
}
# Include annual/one_off: these are long-running individual prediction markets
# (e.g. "Who will be the next Pope?") with the richest price history
TARGET_FREQUENCIES = {'daily', 'weekly', 'monthly', 'quarterly', 'annual', 'one_off'}


# ── Stats computation ─────────────────────────────────────────────────────────

def compute_stats(candles) -> dict:
    """Compute descriptive stats from a list of PricePoint objects."""
    if not candles:
        return {}

    mids = [
        (c.yes_bid + c.yes_ask) / 2.0
        for c in candles
        if c.yes_bid is not None and c.yes_ask is not None
    ]
    spreads = [
        c.yes_ask - c.yes_bid
        for c in candles
        if c.yes_bid is not None and c.yes_ask is not None
    ]
    volumes = [c.volume for c in candles if c.volume is not None]

    price_volatility = 0.0
    if len(mids) >= 2:
        changes = [(mids[i] - mids[i - 1]) / 100.0 for i in range(1, len(mids))]
        try:
            price_volatility = statistics.stdev(changes)
        except statistics.StatisticsError:
            pass

    candles_with_data = sum(
        1 for c in candles if c.yes_bid is not None and c.yes_ask is not None
    )

    return {
        'num_candles': len(candles),
        'data_start_date': candles[0].ts.date(),
        'data_end_date': candles[-1].ts.date(),
        'avg_volume': statistics.mean(volumes) if volumes else 0.0,
        'price_volatility': price_volatility,
        'avg_spread_cents': statistics.mean(spreads) if spreads else 0.0,
        'pct_candles_with_data': candles_with_data / len(candles) if candles else 0.0,
    }


def rank_score(stats: dict) -> float:
    """Composite rank: depth × log(volume+1) / (spread+1)."""
    num = stats.get('num_candles', 0)
    vol = float(stats.get('avg_volume') or 0)
    spread = float(stats.get('avg_spread_cents') or 99)
    pct = float(stats.get('pct_candles_with_data') or 0)
    return (num / 365.0) * math.log1p(vol) * pct / (spread + 1)


# ── DB helpers ────────────────────────────────────────────────────────────────

def upsert_market(session, market, series_ticker: str):
    stmt = pg_insert(Market).values(
        ticker=market.ticker,
        title=market.title,
        category=market.category,
        status=market.status,
        close_date=market.close_time,
        created_at=market.open_time,
        series_ticker=series_ticker,
        event_ticker=market.event_ticker,
    ).on_conflict_do_update(
        index_elements=['ticker'],
        set_={
            'status': market.status,
            'series_ticker': series_ticker,
            'event_ticker': market.event_ticker,
        },
    )
    session.execute(stmt)


def upsert_prices(session, ticker: str, candles) -> int:
    if not candles:
        return 0
    rows = [
        {
            'ticker': ticker,
            'timestamp': c.ts,
            'yes_bid': c.yes_bid,
            'yes_ask': c.yes_ask,
            'volume': c.volume,
        }
        for c in candles
    ]
    stmt = pg_insert(MarketPrice).values(rows).on_conflict_do_nothing(
        index_elements=['ticker', 'timestamp']
    )
    session.execute(stmt)
    return len(rows)


def upsert_market_stats(session, ticker: str, series_ticker: str, stats: dict, score: float):
    stmt = pg_insert(MarketStats).values(
        ticker=ticker,
        series_ticker=series_ticker,
        computed_at=datetime.now(tz=timezone.utc),
        num_candles=stats.get('num_candles'),
        data_start_date=stats.get('data_start_date'),
        data_end_date=stats.get('data_end_date'),
        avg_volume=stats.get('avg_volume'),
        price_volatility=stats.get('price_volatility'),
        avg_spread_cents=stats.get('avg_spread_cents'),
        pct_candles_with_data=stats.get('pct_candles_with_data'),
        rank_score=score,
    ).on_conflict_do_update(
        index_elements=['ticker'],
        set_={
            'computed_at': datetime.now(tz=timezone.utc),
            'num_candles': stats.get('num_candles'),
            'data_start_date': stats.get('data_start_date'),
            'data_end_date': stats.get('data_end_date'),
            'avg_volume': stats.get('avg_volume'),
            'price_volatility': stats.get('price_volatility'),
            'avg_spread_cents': stats.get('avg_spread_cents'),
            'pct_candles_with_data': stats.get('pct_candles_with_data'),
            'rank_score': score,
        },
    )
    session.execute(stmt)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info('Phase 2: Market Selection')
    logger.info('MIN_CANDLES=%d  TARGET_CATEGORIES=%s', MIN_CANDLES, sorted(TARGET_CATEGORIES))

    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=MIN_CANDLES)
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    results = []  # (series_ticker, market_ticker, stats, score)

    with KalshiClient() as client:
        # ── Step 1: Discover candidate series ──────────────────────────────
        logger.info('Fetching all series...')
        all_series = client.get_all_series()
        logger.info('Total series: %d', len(all_series))

        candidates = [
            s for s in all_series
            if s.category in TARGET_CATEGORIES and s.frequency in TARGET_FREQUENCIES
        ]
        logger.info(
            'Candidate series (relevant category + frequency): %d', len(candidates)
        )

        session = get_session()
        try:
            for i, series in enumerate(candidates, 1):
                logger.info(
                    '[%d/%d] %s | %s | %s | %s',
                    i, len(candidates),
                    series.ticker, series.category, series.frequency, series.title[:50],
                )

                # ── Step 2: Find the best market in this series ─────────────
                markets = client.get_markets(series_ticker=series.ticker, limit=200)
                if not markets:
                    logger.debug('  No markets found')
                    time.sleep(0.1)
                    continue

                # Filter to markets opened before the cutoff
                old_enough = [
                    m for m in markets
                    if m.open_time and m.open_time <= cutoff_dt
                ]
                if not old_enough:
                    logger.debug('  No markets older than %d days', MIN_CANDLES)
                    time.sleep(0.1)
                    continue

                # Pick the market with the highest volume as representative
                best = max(old_enough, key=lambda m: m.volume or 0)
                logger.info('  Best market: %s (vol=%.0f, open=%s)',
                            best.ticker, best.volume or 0,
                            best.open_time and best.open_time.date())

                # ── Step 3: Fetch candlestick history ───────────────────────
                candles = client.get_market_candlesticks(
                    series_ticker=series.ticker,
                    market_ticker=best.ticker,
                    period_interval=1440,
                )
                logger.info('  Candles: %d', len(candles))

                if len(candles) < MIN_CANDLES:
                    logger.debug('  Below MIN_CANDLES threshold, skipping')
                    time.sleep(0.15)
                    continue

                # ── Step 4: Compute stats ───────────────────────────────────
                stats = compute_stats(candles)
                score = rank_score(stats)
                logger.info(
                    '  vol=%.1f spread=%.1fc volatility=%.4f pct_data=%.0f%% score=%.4f',
                    stats.get('avg_volume', 0),
                    stats.get('avg_spread_cents', 0),
                    stats.get('price_volatility', 0),
                    stats.get('pct_candles_with_data', 0) * 100,
                    score,
                )

                # ── Step 5: Persist to DB ───────────────────────────────────
                upsert_market(session, best, series.ticker)
                session.flush()
                upsert_prices(session, best.ticker, candles)
                upsert_market_stats(session, best.ticker, series.ticker, stats, score)
                session.commit()

                results.append({
                    'series_ticker': series.ticker,
                    'series_title': series.title,
                    'category': series.category,
                    'frequency': series.frequency,
                    'market_ticker': best.ticker,
                    'num_candles': stats.get('num_candles', 0),
                    'data_start': str(stats.get('data_start_date', '')),
                    'data_end': str(stats.get('data_end_date', '')),
                    'avg_volume': round(stats.get('avg_volume', 0), 2),
                    'avg_spread_cents': round(stats.get('avg_spread_cents', 0), 2),
                    'price_volatility': round(stats.get('price_volatility', 0), 6),
                    'pct_data': round(stats.get('pct_candles_with_data', 0) * 100, 1),
                    'rank_score': round(score, 6),
                })

                time.sleep(0.2)

        except KeyboardInterrupt:
            logger.info('Interrupted — saving partial results')
            session.rollback()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── Step 6: Rank and output ─────────────────────────────────────────────
    results.sort(key=lambda r: r['rank_score'], reverse=True)

    logger.info('\n=== TOP 20 CANDIDATE MARKETS ===')
    for r in results[:20]:
        logger.info(
            '%s (%s %s) | ticker=%s | days=%d | vol=%.0f | spread=%.1fc | score=%.4f',
            r['series_ticker'], r['category'], r['frequency'],
            r['market_ticker'], r['num_candles'],
            r['avg_volume'], r['avg_spread_cents'], r['rank_score'],
        )

    if results:
        with open(OUTPUT_CSV, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        logger.info('\nWrote %d candidates to %s', len(results), OUTPUT_CSV)
    else:
        logger.warning('No candidates found — check MIN_CANDLES (%d) threshold', MIN_CANDLES)


if __name__ == '__main__':
    main()
