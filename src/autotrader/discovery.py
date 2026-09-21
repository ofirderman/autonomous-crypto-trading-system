"""Dynamic market discovery and execution-quality filtering."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .audit import AuditTrail, record
from .costs import CostModel, walk_book
from .interfaces import MarketDataProvider
from .models import Market, MarketSnapshot, OrderSide, ZERO


@dataclass(frozen=True)
class MarketDiscoveryConfig:
    min_volume_24h_quote: Decimal = Decimal("0")
    min_depth_quote: Decimal = Decimal("0")
    max_spread_bps: Decimal = Decimal("100")
    max_round_trip_cost_bps: Decimal = Decimal("250")
    min_ohlcv_rows: int = 50
    sample_notional_quote: Decimal = Decimal("10")
    require_online: bool = True


@dataclass(frozen=True)
class MarketMetrics:
    symbol: str
    price_change_fraction: Decimal | None
    volume_24h_quote: Decimal
    depth_quote: Decimal
    spread_bps: Decimal | None
    volatility_bps: Decimal | None
    estimated_round_trip_cost_bps: Decimal | None


@dataclass(frozen=True)
class MarketEligibility:
    market: Market
    eligible: bool
    reasons: tuple[str, ...]
    metrics: MarketMetrics | None


def close_to_close_volatility_bps(snapshot: MarketSnapshot) -> Decimal | None:
    closes = [c.close for c in snapshot.ohlcv if c.is_closed and c.close > ZERO]
    if len(closes) < 2:
        return None
    returns = [(closes[index] - closes[index - 1]) / closes[index - 1] for index in range(1, len(closes))]
    mean_square = sum((value * value for value in returns), ZERO) / Decimal(len(returns))
    return mean_square.sqrt() * Decimal("10000")


class MarketDiscovery:
    def __init__(self, config: MarketDiscoveryConfig | None = None, cost_model: CostModel | None = None, audit: AuditTrail | None = None):
        self.config = config or MarketDiscoveryConfig()
        self.cost_model = cost_model or CostModel()
        self.audit = audit

    def evaluate(self, snapshot: MarketSnapshot) -> MarketEligibility:
        market = snapshot.market
        ticker = snapshot.ticker
        book = snapshot.order_book
        reasons: list[str] = []
        midpoint = book.midpoint or ticker.last
        volume_quote = ticker.volume_24h * midpoint
        depth_quote = sum((level.price * level.quantity for level in book.bids + book.asks), ZERO)
        spread_bps = (book.spread / midpoint * Decimal("10000")) if book.spread is not None and midpoint > ZERO else None
        bid_slippage = walk_book(book, OrderSide.SELL, self.config.sample_notional_quote / (book.best_bid or Decimal("1")))
        ask_slippage = walk_book(book, OrderSide.BUY, self.config.sample_notional_quote / (book.best_ask or Decimal("1")))
        slippage_bps = max(bid_slippage.slippage_bps or ZERO, ask_slippage.slippage_bps or ZERO)
        round_trip_bps = (spread_bps or Decimal("999999")) + slippage_bps * Decimal("2") + self.cost_model.fee_schedule.rate(False) * Decimal("20000")
        price_change = None
        if snapshot.ohlcv:
            first = snapshot.ohlcv[0].open
            price_change = (snapshot.ohlcv[-1].close - first) / first if first > ZERO else None
        metrics = MarketMetrics(market.symbol, price_change, volume_quote, depth_quote, spread_bps, close_to_close_volatility_bps(snapshot), round_trip_bps)
        if self.config.require_online and market.rules.status.lower() != "online":
            reasons.append("market_not_online")
        if volume_quote < self.config.min_volume_24h_quote:
            reasons.append("insufficient_24h_volume")
        if depth_quote < self.config.min_depth_quote:
            reasons.append("insufficient_order_book_depth")
        requested_base = self.config.sample_notional_quote / (book.best_ask or Decimal("1"))
        if ask_slippage.filled_quantity < requested_base or bid_slippage.filled_quantity < requested_base:
            reasons.append("insufficient_sample_liquidity")
        if spread_bps is None or spread_bps > self.config.max_spread_bps:
            reasons.append("spread_too_wide")
        if round_trip_bps > self.config.max_round_trip_cost_bps:
            reasons.append("estimated_execution_cost_too_high")
        if len(snapshot.ohlcv) < self.config.min_ohlcv_rows:
            reasons.append("insufficient_history")
        result = MarketEligibility(market, not reasons, tuple(reasons), metrics)
        record(self.audit, "market_eligibility", {"symbol": market.symbol, "eligible": result.eligible, "reasons": list(result.reasons), "metrics": metrics.__dict__})
        return result

    def discover(self, provider: MarketDataProvider, symbols: list[str] | None = None, timeframe: str = "1h", limit: int = 200) -> tuple[MarketEligibility, ...]:
        requested = {symbol.upper().replace("-", "/") for symbol in symbols} if symbols else None
        results: list[MarketEligibility] = []
        for market in provider.list_markets():
            if requested is not None and market.symbol not in requested:
                continue
            try:
                results.append(self.evaluate(provider.fetch_snapshot(market.symbol, timeframe, limit)))
            except Exception as exc:
                results.append(MarketEligibility(market, False, (f"market_data_error:{type(exc).__name__}",), None))
        return tuple(results)
