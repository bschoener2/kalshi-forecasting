import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from .auth import load_private_key, build_auth_headers
from .types import Market, PricePoint, Position, Balance

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

    def get_markets(
        self,
        status: Optional[str] = None,
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
            if cursor:
                params['cursor'] = cursor
            data = self._request('GET', '/markets', params=params)
            for m in data.get('markets', []):
                markets.append(self._parse_market(m))
            page += 1
            cursor = data.get('cursor')
            if not cursor:
                break
            if max_pages and page >= max_pages:
                break
            time.sleep(0.25)  # avoid rate limiting between pages
        return markets

    def get_market(self, ticker: str) -> Market:
        data = self._request('GET', f'/markets/{ticker}')
        return self._parse_market(data['market'])

    def get_market_history(
        self,
        ticker: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        period_interval: int = 1440,
    ) -> list[PricePoint]:
        params: dict = {'period_interval': period_interval}
        if start_ts is not None:
            params['min_ts'] = start_ts
        if end_ts is not None:
            params['max_ts'] = end_ts
        try:
            data = self._request('GET', f'/markets/{ticker}/history', params=params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
        return [self._parse_price_point(p) for p in data.get('history', [])]

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

    @staticmethod
    def _parse_market(m: dict) -> Market:
        def parse_dt(s):
            if not s:
                return None
            if isinstance(s, (int, float)):
                return datetime.fromtimestamp(s, tz=timezone.utc)
            return datetime.fromisoformat(s.replace('Z', '+00:00'))

        return Market(
            ticker=m['ticker'],
            title=m.get('title', ''),
            category=m.get('category', ''),
            status=m.get('status', ''),
            open_time=parse_dt(m.get('open_time') or m.get('open_datetime')),
            close_time=parse_dt(
                m.get('close_time') or m.get('expiration_time') or m.get('close_datetime')
            ),
            yes_bid=m.get('yes_bid'),
            yes_ask=m.get('yes_ask'),
            volume=m.get('volume'),
            series_ticker=m.get('series_ticker'),
        )

    @staticmethod
    def _parse_price_point(p: dict) -> PricePoint:
        ts_val = p.get('ts') or p.get('end_period_ts')
        if isinstance(ts_val, (int, float)):
            ts = datetime.fromtimestamp(ts_val, tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(ts_val).replace('Z', '+00:00'))
        return PricePoint(
            ts=ts,
            yes_bid=p.get('yes_bid'),
            yes_ask=p.get('yes_ask'),
            volume=p.get('volume'),
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
