"""Exchange-neutral immutable-ish domain models.

All monetary and quantity values use Decimal. Floats are accepted at integration
boundaries only and are converted through their string representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum
from typing import Any


ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    value, increment = dec(value), dec(increment)
    if increment <= ZERO:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class AssetRules:
    price_increment: Decimal = Decimal("0.00000001")
    quantity_increment: Decimal = Decimal("0.00000001")
    min_quantity: Decimal = ZERO
    min_notional: Decimal = ZERO
    maker_fee: Decimal = Decimal("0.004")
    taker_fee: Decimal = Decimal("0.004")
    status: str = "online"


@dataclass(frozen=True)
class Market:
    symbol: str
    exchange_symbol: str
    base_asset: str
    quote_asset: str
    rules: AssetRules


@dataclass(frozen=True)
class OHLCV:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    vwap: Decimal | None = None
    trade_count: int | None = None
    is_closed: bool = True


@dataclass(frozen=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: datetime

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def midpoint(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass(frozen=True)
class Ticker:
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    timestamp: datetime

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> Decimal:
        if self.bid <= ZERO:
            return ZERO
        return self.spread / self.bid * Decimal("10000")


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    ticker: Ticker
    order_book: OrderBook
    ohlcv: tuple[OHLCV, ...] = ()
    collected_at: datetime = field(default_factory=utc_now)


@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    filled_quantity: Decimal = ZERO
    average_fill_price: Decimal | None = None
    status: OrderStatus = OrderStatus.OPEN
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def remaining_quantity(self) -> Decimal:
        return max(ZERO, self.quantity - self.filled_quantity)


@dataclass(frozen=True)
class Fill:
    id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def gross_quote(self) -> Decimal:
        return self.quantity * self.price


@dataclass
class Position:
    asset: str
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO

    @property
    def average_entry_price(self) -> Decimal:
        return self.cost_basis / self.quantity if self.quantity else ZERO

