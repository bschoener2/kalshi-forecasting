from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Numeric, DateTime, Date, ForeignKey,
    UniqueConstraint, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = 'markets'

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[Optional[str]] = mapped_column(String)
    close_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    series_ticker: Mapped[Optional[str]] = mapped_column(String)

    prices: Mapped[list['MarketPrice']] = relationship(back_populates='market')


class MarketPrice(Base):
    __tablename__ = 'market_prices'
    __table_args__ = (UniqueConstraint('ticker', 'timestamp'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, ForeignKey('markets.ticker'), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    yes_bid: Mapped[Optional[int]] = mapped_column(Integer)
    yes_ask: Mapped[Optional[int]] = mapped_column(Integer)
    volume: Mapped[Optional[int]] = mapped_column(Integer)

    market: Mapped['Market'] = relationship(back_populates='prices')


class Position(Base):
    __tablename__ = 'positions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, ForeignKey('markets.ticker'), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, ForeignKey('markets.ticker'), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # yes_buy/yes_sell/no_buy/no_sell
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    status: Mapped[str] = mapped_column(String, nullable=False)  # PENDING/APPROVED/EXECUTED/REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    notes: Mapped[Optional[str]] = mapped_column(String)


class DailyDecision(Base):
    __tablename__ = 'daily_decisions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(String, ForeignKey('markets.ticker'), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String)
    forecast: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    recommended_action: Mapped[Optional[str]] = mapped_column(String)  # buy/sell/hold
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String, nullable=False, server_default='pending')
