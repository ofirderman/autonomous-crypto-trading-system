"""Minimal Phase 1 market-data CLI; deliberately no trading command."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

from .config import load_config
from .kraken import KrakenPublicAdapter
from .logging import configure_logging
from .market_data import MarketDataCollector


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public Kraken market data (paper-only Phase 1)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--market", default="BTC/USD")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--once", action="store_true", help="required safety acknowledgement for the one-shot collection")
    args = parser.parse_args()
    if not args.once:
        parser.error("--once is required; Phase 1 has no live or continuous trading command")
    config = load_config(args.config)
    configure_logging(config.log_level)
    adapter = KrakenPublicAdapter(config.base_url, config.request_timeout_seconds, default_order_book_depth=config.order_book_depth)
    data = MarketDataCollector(adapter, config.order_book_depth, config.ohlcv_limit).collect(args.market, args.timeframe)
    snapshot = data.snapshot
    print(json.dumps({
        "exchange": "kraken",
        "symbol": snapshot.market.symbol,
        "bid": str(snapshot.ticker.bid),
        "ask": str(snapshot.ticker.ask),
        "last": str(snapshot.ticker.last),
        "spread": str(data.spread) if data.spread is not None else None,
        "spread_bps": str(data.spread_bps) if data.spread_bps is not None else None,
        "ohlcv_rows": len(snapshot.ohlcv),
        "paper_only": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
