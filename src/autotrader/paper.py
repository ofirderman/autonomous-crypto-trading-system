"""Order-book-aware spot paper execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import uuid

from .models import Fill, Market, MarketSnapshot, Order, OrderBook, OrderSide, OrderStatus, OrderType, floor_to_increment, dec, utc_now, ZERO
from .persistence import SQLiteStore
from .portfolio import AccountingError, Portfolio


class PaperExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionConfig:
    default_taker_fee: Decimal = Decimal("0.004")
    market_slippage_bps: Decimal = Decimal("5")


class PaperExecutionEngine:
    def __init__(self, markets: dict[str, Market], portfolio: Portfolio, config: ExecutionConfig | None = None, store: SQLiteStore | None = None):
        self.markets = markets
        self.portfolio = portfolio
        self.config = config or ExecutionConfig()
        self.store = store

    def submit_order(self, symbol: str, side: OrderSide | str, order_type: OrderType | str, quantity: Decimal, limit_price: Decimal | None = None, reference_price: Decimal | None = None) -> Order:
        market = self._market(symbol)
        side = OrderSide(side)
        order_type = OrderType(order_type)
        qty = floor_to_increment(dec(quantity), market.rules.quantity_increment)
        if qty < market.rules.min_quantity:
            raise PaperExecutionError("quantity is below the market minimum")
        estimate = dec(limit_price if order_type is OrderType.LIMIT else reference_price or ZERO)
        if estimate <= ZERO:
            raise PaperExecutionError("a positive reference price is required for a market order")
        if qty * estimate < market.rules.min_notional:
            raise PaperExecutionError("order notional is below the market minimum")
        if order_type is OrderType.LIMIT and limit_price is None:
            raise PaperExecutionError("limit orders require limit_price")
        if limit_price is not None:
            limit_price = floor_to_increment(dec(limit_price), market.rules.price_increment)
        order = Order(str(uuid.uuid4()), market.symbol, side, order_type, qty, limit_price)
        fee_rate = market.rules.taker_fee if order_type is OrderType.MARKET else market.rules.maker_fee
        if not fee_rate:
            fee_rate = self.config.default_taker_fee
        # Reserve a slippage cushion for market buys, preventing a book move from
        # silently spending unreserved cash.
        if order_type is OrderType.MARKET and side is OrderSide.BUY:
            estimate *= Decimal("1") + self.config.market_slippage_bps / Decimal("10000")
        try:
            self.portfolio.register_order(order, market, estimate, fee_rate)
        except AccountingError as exc:
            raise PaperExecutionError(str(exc)) from exc
        self._save_order(order)
        return order

    def process_snapshot(self, snapshot: MarketSnapshot) -> tuple[Fill, ...]:
        fills: list[Fill] = []
        for order in list(self.portfolio.orders.values()):
            if order.symbol != snapshot.market.symbol or order.status not in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
                continue
            fills.extend(self._match(order, snapshot.market, snapshot.order_book))
        if self.store:
            self.store.snapshot(self.portfolio)
        return tuple(fills)

    def cancel_order(self, order_id: str) -> None:
        try:
            order = self.portfolio.orders[order_id]
        except KeyError as exc:
            raise PaperExecutionError(f"unknown order: {order_id}") from exc
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED):
            return
        self.portfolio.finalize_order(order_id, canceled=True)
        self._save_order(order)

    def _match(self, order: Order, market: Market, book: OrderBook) -> list[Fill]:
        levels = book.asks if order.side is OrderSide.BUY else book.bids
        eligible = []
        for level in levels:
            if order.type is OrderType.LIMIT:
                if order.side is OrderSide.BUY and level.price > order.limit_price:
                    break
                if order.side is OrderSide.SELL and level.price < order.limit_price:
                    break
            eligible.append(level)
        fills: list[Fill] = []
        remaining = order.remaining_quantity
        for level in eligible:
            if remaining <= ZERO:
                break
            qty = floor_to_increment(min(remaining, level.quantity), market.rules.quantity_increment)
            if qty <= ZERO:
                continue
            price = level.price
            if order.type is OrderType.MARKET:
                slippage = self.config.market_slippage_bps / Decimal("10000")
                price = price * (Decimal("1") + slippage if order.side is OrderSide.BUY else Decimal("1") - slippage)
                price = floor_to_increment(price, market.rules.price_increment)
            fee_rate = market.rules.taker_fee if order.type is OrderType.MARKET else market.rules.maker_fee
            fee_rate = fee_rate or self.config.default_taker_fee
            fee = qty * price * fee_rate
            fill = Fill(str(uuid.uuid4()), order.id, order.symbol, order.side, qty, price, fee, market.quote_asset)
            try:
                self.portfolio.apply_fill(fill, market)
            except AccountingError:
                break
            fills.append(fill)
            remaining = order.remaining_quantity
            if self.store:
                self.store.record_fill(fill)
        order.updated_at = utc_now()
        if order.remaining_quantity == ZERO:
            self.portfolio.finalize_order(order.id)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED if order.filled_quantity else OrderStatus.OPEN
        self._save_order(order)
        return fills

    def _market(self, symbol: str) -> Market:
        canonical = symbol.upper().replace("-", "/")
        try:
            return self.markets[canonical]
        except KeyError as exc:
            raise PaperExecutionError(f"unknown paper market: {symbol}") from exc

    def _save_order(self, order: Order) -> None:
        if self.store:
            self.store.record_order(order)
