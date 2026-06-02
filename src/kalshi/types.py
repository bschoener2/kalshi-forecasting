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
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    volume: Optional[int]
    series_ticker: Optional[str]


@dataclass
class PricePoint:
    ts: datetime
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    volume: Optional[int]


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
