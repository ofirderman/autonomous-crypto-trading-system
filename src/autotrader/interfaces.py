"""Stable boundaries between domain logic and exchange integrations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence

from .models import Market, OHLCV, OrderBook, MarketSnapshot, Ticker


class MarketDataProvider(Protocol):
    def list_markets(self) -> Sequence[Market]: ...
    def fetch_ticker(self, symbol: str) -> Ticker: ...
    def fetch_order_book(self, symbol: str, depth: int = 25) -> OrderBook: ...
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> Sequence[OHLCV]: ...
    def fetch_snapshot(self, symbol: str, timeframe: str = "1h", limit: int = 200, depth: int = 25) -> MarketSnapshot: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class ExecutionVenue(Protocol):
    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        limit_price: Decimal | None = None,
        reference_price: Decimal | None = None,
    ): ...
