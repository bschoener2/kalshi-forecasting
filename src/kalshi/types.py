from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Market:
    ticker: str
    title: str
    category: str
    status: str
    open_time: Optional[datetime]
    close_time: Optional[datetime]
    yes_bid: Optional[int]    # cents (0-99)
    yes_ask: Optional[int]    # cents (0-99)
    volume: Optional[float]
    series_ticker: Optional[str]
    event_ticker: Optional[str]


@dataclass
class PricePoint:
    ts: datetime
    yes_bid: Optional[int]    # cents
    yes_ask: Optional[int]    # cents
    volume: Optional[float]


@dataclass
class SeriesInfo:
    ticker: str
    title: str
    category: str
    frequency: str


@dataclass
class Position:
    ticker: str
    quantity: int
    market_exposure: int
    realized_pnl: int
    unrealized_pnl: int


@dataclass
class Balance:
    available_balance_cents: int
    portfolio_value_cents: int
    total_value_cents: int
