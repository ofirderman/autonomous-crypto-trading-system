"""Independent risk approval layer between strategy proposals and execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping

from .audit import AuditTrail, record
from .conversion import ConversionError, ConversionRates
from .costs import CostModel, walk_book
from .models import MarketSnapshot, OrderSide, OrderStatus, ZERO
from .portfolio import Portfolio
from .strategy import TradeProposal


@dataclass(frozen=True)
class RiskConfig:
    accounting_currency: str = "USD"
    initial_capital: Decimal = Decimal("118.85")
    max_gross_exposure_fraction: Decimal = Decimal("0.80")
    max_position_fraction: Decimal = Decimal("0.25")
    max_position_risk_fraction: Decimal = Decimal("0.02")
    max_concurrent_positions: int = 3
    max_spread_bps: Decimal = Decimal("100")
    max_slippage_bps: Decimal = Decimal("100")
    stale_after: timedelta = timedelta(minutes=5)
    max_drawdown_fraction: Decimal = Decimal("0.10")
    emergency_shutdown: bool = False

    def __post_init__(self) -> None:
        fractions = (self.max_gross_exposure_fraction, self.max_position_fraction, self.max_position_risk_fraction, self.max_drawdown_fraction)
        if any(value < ZERO or value > Decimal("1") for value in fractions):
            raise ValueError("risk fractions must be between 0 and 1")
        if self.initial_capital <= ZERO or self.max_concurrent_positions < 1 or self.max_spread_bps < ZERO or self.max_slippage_bps < ZERO:
            raise ValueError("risk limits must be positive or non-negative where appropriate")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    estimated_equity: Decimal
    estimated_exposure: Decimal
    estimated_position_risk: Decimal


class DrawdownMonitor:
    def __init__(self, initial_capital: Decimal):
        self.high_watermark = Decimal(str(initial_capital))

    def update(self, equity: Decimal) -> Decimal:
        equity = Decimal(str(equity))
        self.high_watermark = max(self.high_watermark, equity)
        return (self.high_watermark - equity) / self.high_watermark if self.high_watermark else Decimal("0")


class RiskEngine:
    def __init__(self, config: RiskConfig | None = None, cost_model: CostModel | None = None, audit: AuditTrail | None = None):
        self.config = config or RiskConfig()
        self.cost_model = cost_model or CostModel()
        self.audit = audit
        self.shutdown_reason: str | None = "configured_shutdown" if self.config.emergency_shutdown else None
        self.drawdown = DrawdownMonitor(self.config.initial_capital)

    @property
    def halted(self) -> bool:
        return self.shutdown_reason is not None

    def halt(self, reason: str) -> None:
        self.shutdown_reason = reason or "manual_shutdown"
        record(self.audit, "emergency_shutdown", {"reason": self.shutdown_reason})

    def resume(self) -> None:
        self.shutdown_reason = None
        record(self.audit, "emergency_resume", {})

    def approve(self, proposal: TradeProposal, snapshot: MarketSnapshot, portfolio: Portfolio,
                conversions: ConversionRates | None = None, position_marks: Mapping[str, tuple[Decimal, str]] | None = None,
                now: datetime | None = None) -> RiskDecision:
        conversions = conversions or ConversionRates()
        position_marks = position_marks or {}
        now = now or datetime.now(timezone.utc)
        reasons: list[str] = []
        market = snapshot.market
        quote = market.quote_asset
        entry = snapshot.order_book.best_ask or snapshot.ticker.ask
        try:
            equity = self._equity_usd(portfolio, conversions, position_marks, snapshot)
            current_exposure = self._exposure_usd(portfolio, conversions, position_marks, snapshot)
        except ConversionError:
            equity = Decimal("0")
            current_exposure = Decimal("0")
            reasons.append("missing_accounting_conversion_or_mark")
        proposed_exposure = Decimal("0")
        position_risk = Decimal("0")
        if self.halted:
            reasons.append("emergency_shutdown")
        if now - snapshot.collected_at > self.config.stale_after:
            reasons.append("stale_market_data")
        if market.rules.status.lower() != "online":
            reasons.append("market_not_online")
        if proposal.symbol != market.symbol:
            reasons.append("proposal_market_mismatch")
        if snapshot.order_book.spread is None:
            reasons.append("missing_order_book_spread")
        elif snapshot.ticker.spread_bps > self.config.max_spread_bps:
            reasons.append("spread_limit")
        if proposal.direction.value != "long":
            reasons.append("spot_long_only")
        try:
            proposal.validate(entry)
        except ValueError as exc:
            reasons.append(f"invalid_proposal:{str(exc)}")
        quantity = proposal.proposed_position_size
        rounded_quantity = quantity
        if market.rules.quantity_increment > 0:
            from .models import floor_to_increment
            rounded_quantity = floor_to_increment(quantity, market.rules.quantity_increment)
        if rounded_quantity < market.rules.min_quantity:
            reasons.append("minimum_quantity")
        if rounded_quantity * entry < market.rules.min_notional:
            reasons.append("minimum_notional")
        if self._duplicate_order(portfolio, market.symbol):
            reasons.append("duplicate_order")
        if market.base_asset not in portfolio.positions or portfolio.positions[market.base_asset].quantity <= 0:
            open_positions = sum(1 for position in portfolio.positions.values() if position.quantity > 0)
            if open_positions >= self.config.max_concurrent_positions:
                reasons.append("maximum_concurrent_positions")
        try:
            quote_to_usd = conversions.get(quote, self.config.accounting_currency)
            if quote != self.config.accounting_currency and quote_to_usd is None:
                raise ConversionError("missing quote conversion")
            proposed_exposure = conversions.convert(rounded_quantity * entry, quote, self.config.accounting_currency)
            expected = self.cost_model.estimate_round_trip(market, snapshot.order_book, rounded_quantity, proposal.stop_loss)
            position_risk = conversions.convert(abs(expected.gross_pnl) + expected.total_cost, quote, self.config.accounting_currency)
            slippage_buy = walk_book(snapshot.order_book, OrderSide.BUY, rounded_quantity)
            if slippage_buy.slippage_bps is not None and slippage_buy.slippage_bps > self.config.max_slippage_bps:
                reasons.append("slippage_limit")
        except (ConversionError, ValueError):
            reasons.append("missing_cost_inputs")
        fee_rate = self.cost_model.fee_schedule.rate(False)
        if portfolio.free(quote) < rounded_quantity * entry * (Decimal("1") + fee_rate):
            reasons.append("insufficient_available_balance")
        if equity <= 0:
            reasons.append("non_positive_equity")
        else:
            if current_exposure + proposed_exposure > equity * self.config.max_gross_exposure_fraction:
                reasons.append("maximum_gross_exposure")
            if proposed_exposure > equity * self.config.max_position_fraction:
                reasons.append("maximum_position_exposure")
            if position_risk > equity * self.config.max_position_risk_fraction:
                reasons.append("maximum_position_risk")
            if self.drawdown.update(equity) > self.config.max_drawdown_fraction:
                reasons.append("maximum_drawdown")
        decision = RiskDecision(not reasons, tuple(reasons), equity, current_exposure + proposed_exposure, position_risk)
        record(self.audit, "risk_decision", {"symbol": proposal.symbol, "strategy": proposal.strategy_name, "approved": decision.approved, "reasons": list(decision.reasons), "estimated_equity": str(equity), "estimated_exposure": str(decision.estimated_exposure), "estimated_position_risk": str(position_risk)})
        return decision

    @staticmethod
    def _duplicate_order(portfolio: Portfolio, symbol: str) -> bool:
        return any(order.symbol == symbol and order.side is OrderSide.BUY and order.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED) for order in portfolio.orders.values())

    def _equity_usd(self, portfolio: Portfolio, conversions: ConversionRates, marks: Mapping[str, tuple[Decimal, str]], snapshot: MarketSnapshot) -> Decimal:
        total = Decimal("0")
        position_assets = set(portfolio.positions)
        for asset in set(portfolio.available) | set(portfolio.reserved):
            if asset in position_assets:
                continue
            total += conversions.convert(portfolio.balance(asset), asset, self.config.accounting_currency)
        total += self._position_value_usd(portfolio, conversions, marks, snapshot)
        return total

    def _exposure_usd(self, portfolio: Portfolio, conversions: ConversionRates, marks: Mapping[str, tuple[Decimal, str]], snapshot: MarketSnapshot) -> Decimal:
        return self._position_value_usd(portfolio, conversions, marks, snapshot)

    def _position_value_usd(self, portfolio: Portfolio, conversions: ConversionRates, marks: Mapping[str, tuple[Decimal, str]], snapshot: MarketSnapshot) -> Decimal:
        total = Decimal("0")
        for asset, position in portfolio.positions.items():
            if position.quantity <= 0:
                continue
            if asset == snapshot.market.base_asset:
                price, quote = snapshot.ticker.bid, snapshot.market.quote_asset
            elif asset in marks:
                price, quote = marks[asset]
            else:
                raise ConversionError(f"missing mark for open position {asset}")
            total += conversions.convert(position.quantity * price, quote, self.config.accounting_currency)
        return total
