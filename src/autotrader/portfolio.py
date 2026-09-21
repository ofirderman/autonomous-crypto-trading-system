"""Double-entry-like spot portfolio accounting.

Reservations are tracked independently from available balances. A sell can only
reserve owned base inventory; a buy can only reserve quote cash. There is no
shorting, leverage, or negative balance path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

from .models import Fill, Market, Order, OrderSide, OrderStatus, Position, ZERO, dec


class AccountingError(ValueError):
    pass


@dataclass
class Portfolio:
    available: dict[str, Decimal] = field(default_factory=dict)
    reserved: dict[str, Decimal] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    realized_pnl: Decimal = ZERO
    total_fees: Decimal = ZERO
    _reservations: dict[str, tuple[str, Decimal]] = field(default_factory=dict, repr=False)

    @classmethod
    def with_cash(cls, asset: str, amount: Decimal) -> "Portfolio":
        return cls(available={asset: dec(amount)}, reserved={asset: ZERO})

    def balance(self, asset: str) -> Decimal:
        return self.available.get(asset, ZERO) + self.reserved.get(asset, ZERO)

    def free(self, asset: str) -> Decimal:
        return self.available.get(asset, ZERO)

    def _add_available(self, asset: str, amount: Decimal) -> None:
        value = self.available.get(asset, ZERO) + amount
        if value < ZERO:
            raise AccountingError(f"negative available balance for {asset}")
        self.available[asset] = value

    def _add_reserved(self, asset: str, amount: Decimal) -> None:
        value = self.reserved.get(asset, ZERO) + amount
        if value < ZERO:
            raise AccountingError(f"negative reserved balance for {asset}")
        self.reserved[asset] = value

    def register_order(self, order: Order, market: Market, estimate_price: Decimal, fee_rate: Decimal) -> None:
        if order.id in self.orders:
            raise AccountingError(f"duplicate order id: {order.id}")
        if order.quantity <= ZERO:
            raise AccountingError("order quantity must be positive")
        if order.side is OrderSide.BUY:
            reserve = order.quantity * dec(estimate_price) * (Decimal("1") + dec(fee_rate))
            asset = market.quote_asset
        else:
            reserve = order.quantity
            asset = market.base_asset
        if self.free(asset) < reserve:
            raise AccountingError(f"insufficient available {asset}: need {reserve}, have {self.free(asset)}")
        self._add_available(asset, -reserve)
        self._add_reserved(asset, reserve)
        self._reservations[order.id] = (asset, reserve)
        self.orders[order.id] = order

    def _consume_reservation(self, order_id: str, amount: Decimal) -> None:
        asset, remaining = self._reservations[order_id]
        consumed = min(remaining, amount)
        self._add_reserved(asset, -consumed)
        self._reservations[order_id] = (asset, remaining - consumed)

    def release_order(self, order_id: str) -> None:
        if order_id not in self._reservations:
            return
        asset, amount = self._reservations.pop(order_id)
        self._add_reserved(asset, -amount)
        self._add_available(asset, amount)

    def apply_fill(self, fill: Fill, market: Market) -> None:
        order = self.orders[fill.order_id]
        gross = fill.gross_quote
        fee = dec(fill.fee)
        if fill.quantity <= ZERO or fill.price <= ZERO:
            raise AccountingError("fill quantity and price must be positive")
        if fill.quantity > order.remaining_quantity:
            raise AccountingError("fill exceeds order remaining quantity")
        if fill.side is OrderSide.BUY:
            reserved_asset, reserved_amount = self._reservations[fill.order_id]
            extra = max(ZERO, gross + fee - reserved_amount)
            if extra:
                if self.free(reserved_asset) < extra:
                    raise AccountingError("fill requires more quote cash than reserved")
                self._add_available(reserved_asset, -extra)
            self._consume_reservation(fill.order_id, gross + fee)
            self._add_available(market.base_asset, fill.quantity)
            position = self.positions.setdefault(market.base_asset, Position(market.base_asset))
            position.quantity += fill.quantity
            position.cost_basis += gross + fee
        else:
            self._consume_reservation(fill.order_id, fill.quantity)
            position = self.positions.setdefault(market.base_asset, Position(market.base_asset))
            if position.quantity < fill.quantity:
                raise AccountingError("sell exceeds owned position")
            cost = position.average_entry_price * fill.quantity
            position.quantity -= fill.quantity
            position.cost_basis -= cost
            self._add_available(market.quote_asset, gross - fee)
            self.realized_pnl += gross - fee - cost
        self.total_fees += fee
        order.filled_quantity += fill.quantity
        prior_notional = (order.average_fill_price or ZERO) * (order.filled_quantity - fill.quantity)
        order.average_fill_price = (prior_notional + gross) / order.filled_quantity

    def finalize_order(self, order_id: str, canceled: bool = False) -> None:
        order = self.orders[order_id]
        if canceled:
            order.status = OrderStatus.CANCELED
        elif order.remaining_quantity == ZERO:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED if order.filled_quantity else OrderStatus.OPEN
        self.release_order(order_id)

    def unrealized_pnl(self, marks: Mapping[str, Decimal]) -> Decimal:
        return sum((dec(marks.get(asset, ZERO)) * position.quantity - position.cost_basis for asset, position in self.positions.items()), ZERO)

    def equity(self, quote_asset: str, marks: Mapping[str, Decimal]) -> Decimal:
        total = self.balance(quote_asset)
        for asset, position in self.positions.items():
            total += position.quantity * dec(marks.get(asset, ZERO))
        return total
