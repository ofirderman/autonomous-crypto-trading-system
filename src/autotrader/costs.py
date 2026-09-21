"""Fee-aware and liquidity-aware execution cost calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import Market, OrderBook, OrderSide, ZERO, dec


@dataclass(frozen=True)
class FeeTier:
    """A maker/taker tier selected by cumulative quote volume."""

    volume_threshold: Decimal
    maker_rate: Decimal
    taker_rate: Decimal


@dataclass(frozen=True)
class FeeSchedule:
    tiers: tuple[FeeTier, ...] = (FeeTier(Decimal("0"), Decimal("0.004"), Decimal("0.004")),)

    def __post_init__(self) -> None:
        if not self.tiers:
            raise ValueError("fee schedule needs at least one tier")
        if any(t.volume_threshold < ZERO or t.maker_rate < ZERO or t.taker_rate < ZERO for t in self.tiers):
            raise ValueError("fee thresholds and rates cannot be negative")

    def rate(self, maker: bool = False, cumulative_volume: Decimal = ZERO) -> Decimal:
        eligible = [tier for tier in self.tiers if tier.volume_threshold <= cumulative_volume]
        tier = max(eligible or [self.tiers[0]], key=lambda item: item.volume_threshold)
        return tier.maker_rate if maker else tier.taker_rate


@dataclass(frozen=True)
class SlippageEstimate:
    side: OrderSide
    requested_quantity: Decimal
    filled_quantity: Decimal
    reference_price: Decimal
    volume_weighted_price: Decimal | None
    slippage_bps: Decimal | None


@dataclass(frozen=True)
class RoundTripCost:
    entry_notional: Decimal
    exit_notional: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    spread_cost: Decimal
    entry_slippage: Decimal
    exit_slippage: Decimal
    conversion_cost: Decimal
    total_cost: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal

    @property
    def net_return_fraction(self) -> Decimal:
        return self.net_pnl / self.entry_notional if self.entry_notional else ZERO


def walk_book(book: OrderBook, side: OrderSide, quantity: Decimal) -> SlippageEstimate:
    """Estimate a market order by walking displayed levels without mutating them."""

    quantity = dec(quantity)
    levels = book.asks if side is OrderSide.BUY else book.bids
    reference = book.best_ask if side is OrderSide.BUY else book.best_bid
    if reference is None or reference <= ZERO:
        return SlippageEstimate(side, quantity, ZERO, ZERO, None, None)
    remaining = quantity
    notional = ZERO
    filled = ZERO
    for level in levels:
        take = min(remaining, level.quantity)
        if take <= ZERO:
            continue
        notional += take * level.price
        filled += take
        remaining -= take
        if remaining <= ZERO:
            break
    if filled <= ZERO:
        return SlippageEstimate(side, quantity, ZERO, reference, None, None)
    vwap = notional / filled
    slippage = (vwap - reference) / reference * Decimal("10000")
    if side is OrderSide.SELL:
        slippage = -slippage
    return SlippageEstimate(side, quantity, filled, reference, vwap, max(ZERO, slippage))


class CostModel:
    def __init__(self, fee_schedule: FeeSchedule | None = None, slippage_bps: Decimal = Decimal("5"), conversion_cost_bps: Decimal = ZERO):
        self.fee_schedule = fee_schedule or FeeSchedule()
        self.slippage_bps = dec(slippage_bps)
        self.conversion_cost_bps = dec(conversion_cost_bps)
        if self.slippage_bps < ZERO or self.conversion_cost_bps < ZERO:
            raise ValueError("cost assumptions cannot be negative")

    def estimate_round_trip(self, market: Market, book: OrderBook, quantity: Decimal, exit_price: Decimal,
                            maker_entry: bool = False, maker_exit: bool = False,
                            cumulative_volume: Decimal = ZERO, conversion_notional: Decimal = ZERO) -> RoundTripCost:
        quantity = dec(quantity)
        entry = book.best_ask
        bid = book.best_bid
        if entry is None or bid is None:
            raise ValueError("order book must contain both bid and ask")
        entry_notional = quantity * entry
        exit_notional = quantity * dec(exit_price)
        entry_fee = entry_notional * self.fee_schedule.rate(maker_entry, cumulative_volume)
        exit_fee = exit_notional * self.fee_schedule.rate(maker_exit, cumulative_volume)
        entry_walk = walk_book(book, OrderSide.BUY, quantity)
        if entry_walk.filled_quantity < quantity:
            raise ValueError("insufficient displayed ask liquidity for requested quantity")
        exit_walk = SlippageEstimate(OrderSide.SELL, quantity, quantity, bid, bid, ZERO)
        entry_slippage = entry_notional * self.slippage_bps / Decimal("10000")
        exit_slippage = exit_notional * self.slippage_bps / Decimal("10000")
        if entry_walk.slippage_bps is not None:
            entry_slippage += entry_notional * entry_walk.slippage_bps / Decimal("10000")
        spread_cost = quantity * (entry - bid)
        conversion_cost = dec(conversion_notional) * self.conversion_cost_bps / Decimal("10000")
        total_cost = entry_fee + exit_fee + spread_cost + entry_slippage + exit_slippage + conversion_cost
        gross_pnl = exit_notional - entry_notional
        return RoundTripCost(entry_notional, exit_notional, entry_fee, exit_fee, spread_cost, entry_slippage, exit_slippage, conversion_cost, total_cost, gross_pnl, gross_pnl - total_cost)
