import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from .auth import load_private_key, build_auth_headers
from .types import Market, PricePoint, SeriesInfo, Position, Balance

logger = logging.getLogger(__name__)

BASE_URL = 'https://api.elections.kalshi.com/trade-api/v2'
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


class KalshiClient:
    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        base_url: str = BASE_URL,
    ):
        self.api_key_id = api_key_id or os.environ['KALSHI_API_KEY_ID']
        key_path = private_key_path or os.environ['KALSHI_PRIVATE_KEY_PATH']
        self.private_key = load_private_key(key_path)
        self.base_url = base_url.rstrip('/')
        # Kalshi signs the full URL path (e.g. /trade-api/v2/portfolio/balance)
        self._base_path = urlparse(self.base_url).path.rstrip('/')
        self._client = httpx.Client(timeout=30.0)

    def _request(self, method: str, path: str, params: dict = None) -> dict:
        url = self.base_url + path
        full_path = self._base_path + path
        for attempt in range(MAX_RETRIES):
            # Regenerate headers each attempt so the timestamp is always fresh
            headers = build_auth_headers(self.api_key_id, self.private_key, method, full_path)
            try:
                resp = self._client.request(method, url, headers=headers, params=params)
                if resp.status_code == 429:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning('Rate limited; sleeping %.1fs', wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning('Server error %d; sleeping %.1fs', resp.status_code, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError:
                if attempt == MAX_RETRIES - 1:
                    raise
        raise RuntimeError(f'Max retries exceeded for {method} {path}')

    # ── Series ────────────────────────────────────────────────────────────

    def get_all_series(self) -> list[SeriesInfo]:
        series = []
        cursor = None
        while True:
            params: dict = {'limit': 200}
            if cursor:
                params['cursor'] = cursor
            data = self._request('GET', '/series', params=params)
            for s in data.get('series', []):
                series.append(SeriesInfo(
                    ticker=s['ticker'],
                    title=s.get('title', ''),
                    category=s.get('category', ''),
                    frequency=s.get('frequency', ''),
                ))
            cursor = data.get('cursor')
            if not cursor:
                break
            time.sleep(0.12)
        return series

    # ── Markets ───────────────────────────────────────────────────────────

    def get_markets(
        self,
        status: Optional[str] = None,
        series_ticker: Optional[str] = None,
        limit: int = 200,
        max_pages: Optional[int] = None,
    ) -> list[Market]:
        markets = []
        cursor = None
        page = 0
        while True:
            params: dict = {'limit': limit}
            if status:
                params['status'] = status
            if series_ticker:
                params['series_ticker'] = series_ticker
            if cursor:
                params['cursor'] = cursor
            data = self._request('GET', '/markets', params=params)
            for m in data.get('markets', []):
                parsed = self._parse_market(m)
                # Ensure series_ticker is populated when we know it from the query
                if series_ticker and not parsed.series_ticker:
                    parsed.series_ticker = series_ticker
                markets.append(parsed)
            page += 1
            cursor = data.get('cursor')
            if not cursor:
                break
            if max_pages and page >= max_pages:
                break
            time.sleep(0.25)
        return markets

    def get_market(self, ticker: str) -> Market:
        data = self._request('GET', f'/markets/{ticker}')
        return self._parse_market(data['market'])

    # ── Candlesticks ─────────────────────────────────────────────────────

    def get_market_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        period_interval: int = 1440,
    ) -> list[PricePoint]:
        """Fetch OHLC candlestick data.

        Endpoint: GET /series/{series_ticker}/markets/{market_ticker}/candlesticks
        period_interval is in minutes (1440 = daily).
        The API requires start_ts/end_ts; defaults to a 2-year lookback if not provided.
        """
        now = int(time.time())
        params: dict = {
            'period_interval': period_interval,
            'start_ts': start_ts if start_ts is not None else now - 86400 * 730,
            'end_ts': end_ts if end_ts is not None else now,
        }
        path = f'/series/{series_ticker}/markets/{market_ticker}/candlesticks'
        try:
            data = self._request('GET', path, params=params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 400):
                return []
            raise
        return [self._parse_candlestick(c) for c in data.get('candlesticks', [])]

    # ── Portfolio ─────────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        data = self._request('GET', '/portfolio/positions')
        return [
            Position(
                ticker=p['ticker'],
                quantity=p.get('position', 0),
                market_exposure=p.get('market_exposure', 0),
                realized_pnl=p.get('realized_pnl', 0),
                unrealized_pnl=p.get('unrealized_pnl', 0),
            )
            for p in data.get('market_positions', [])
        ]

    def get_balance(self) -> Balance:
        data = self._request('GET', '/portfolio/balance')
        return Balance(
            available_balance_cents=data.get('available_balance_cents', 0),
            portfolio_value_cents=data.get('portfolio_value', 0),
            total_value_cents=data.get('total_value', 0),
        )

    # ── Parsers ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_market(m: dict) -> Market:
        def parse_dt(s):
            if not s:
                return None
            if isinstance(s, (int, float)):
                return datetime.fromtimestamp(s, tz=timezone.utc)
            return datetime.fromisoformat(s.replace('Z', '+00:00'))

        def dollars_to_cents(v) -> Optional[int]:
            if v is None:
                return None
            return int(float(v) * 100)

        return Market(
            ticker=m['ticker'],
            title=m.get('title', ''),
            category=m.get('category', ''),
            status=m.get('status', ''),
            open_time=parse_dt(m.get('open_time') or m.get('open_datetime')),
            close_time=parse_dt(
                m.get('close_time') or m.get('expiration_time') or m.get('close_datetime')
            ),
            yes_bid=dollars_to_cents(m.get('yes_bid_dollars')),
            yes_ask=dollars_to_cents(m.get('yes_ask_dollars')),
            volume=float(m['volume_fp']) if m.get('volume_fp') is not None else None,
            series_ticker=m.get('series_ticker') or None,
            event_ticker=m.get('event_ticker') or None,
        )

    @staticmethod
    def _parse_candlestick(c: dict) -> PricePoint:
        ts = datetime.fromtimestamp(c['end_period_ts'], tz=timezone.utc)

        def cents(nested: dict, key: str = 'close_dollars') -> Optional[int]:
            if not nested:
                return None
            v = nested.get(key)
            return int(float(v) * 100) if v else None

        return PricePoint(
            ts=ts,
            yes_bid=cents(c.get('yes_bid')),
            yes_ask=cents(c.get('yes_ask')),
            volume=float(c['volume_fp']) if c.get('volume_fp') is not None else None,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
