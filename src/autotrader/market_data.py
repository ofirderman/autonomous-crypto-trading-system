"""Collection and normalization orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .interfaces import MarketDataProvider
from .models import MarketSnapshot


@dataclass(frozen=True)
class NormalizedSnapshot:
    snapshot: MarketSnapshot
    spread: Decimal | None
    spread_bps: Decimal | None


class MarketDataCollector:
    def __init__(self, provider: MarketDataProvider, order_book_depth: int = 25, ohlcv_limit: int = 200):
        self.provider = provider
        self.order_book_depth = order_book_depth
        self.ohlcv_limit = ohlcv_limit

    def collect(self, symbol: str, timeframe: str = "1h") -> NormalizedSnapshot:
        snapshot = self.provider.fetch_snapshot(symbol, timeframe, self.ohlcv_limit)
        spread = snapshot.order_book.spread
        midpoint = snapshot.order_book.midpoint
        spread_bps = (spread / midpoint * Decimal("10000")) if spread is not None and midpoint else None
        return NormalizedSnapshot(snapshot, spread, spread_bps)

