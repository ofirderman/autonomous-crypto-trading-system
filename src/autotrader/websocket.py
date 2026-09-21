"""Future continuous-market-monitoring interface.

Phase 2 deliberately does not open a websocket. This module defines the event
and subscription boundary so a later transport can be added without coupling
strategies or risk management to Kraken protocol details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, Sequence

from .models import utc_now


@dataclass(frozen=True)
class MarketStreamEvent:
    channel: str
    symbol: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=utc_now)


MarketEventHandler = Callable[[MarketStreamEvent], None]


class MarketDataStream(Protocol):
    def connect(self) -> None: ...
    def subscribe(self, channels: Sequence[str], symbols: Sequence[str], handler: MarketEventHandler) -> None: ...
    def close(self) -> None: ...


class KrakenWebSocketV2Interface:
    """Subscription contract only; transport implementation is intentionally deferred."""

    endpoint = "wss://ws.kraken.com/v2"

    def __init__(self) -> None:
        self.connected = False
        self.subscriptions: list[dict[str, Any]] = []

    def connect(self) -> None:
        raise NotImplementedError("Phase 2 designs the websocket boundary; transport is not enabled")

    def subscribe(self, channels: Sequence[str], symbols: Sequence[str], handler: MarketEventHandler) -> None:
        if not channels or not symbols:
            raise ValueError("websocket subscriptions require channels and symbols")
        self.subscriptions.append({"method": "subscribe", "params": {"channel": list(channels), "symbol": list(symbols)}, "handler": handler})

    def close(self) -> None:
        self.connected = False

