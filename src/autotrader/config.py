"""Configuration loading with a fail-closed live-trading boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import tomllib


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class AppConfig:
    exchange: str = "kraken"
    paper_only: bool = True
    live_trading_enabled: bool = False
    database_path: str = "data/trading.sqlite3"
    log_level: str = "INFO"
    initial_quote_asset: str = "USD"
    initial_cash: Decimal = Decimal("118.85")
    default_taker_fee: Decimal = Decimal("0.004")
    market_slippage_bps: Decimal = Decimal("5")
    base_url: str = "https://api.kraken.com/0/public"
    order_book_depth: int = 25
    ohlcv_limit: int = 200
    request_timeout_seconds: int = 15


def load_config(path: str | Path | None = None) -> AppConfig:
    raw: dict = {}
    if path is not None:
        config_path = Path(path)
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    system = raw.get("system", {})
    paper = raw.get("paper", {})
    market_data = raw.get("market_data", {})
    cfg = AppConfig(
        exchange=str(system.get("exchange", "kraken")),
        paper_only=bool(system.get("paper_only", True)),
        live_trading_enabled=bool(system.get("live_trading_enabled", False)),
        database_path=str(system.get("database_path", "data/trading.sqlite3")),
        log_level=str(system.get("log_level", "INFO")),
        initial_quote_asset=str(paper.get("initial_quote_asset", "USD")),
        initial_cash=Decimal(str(paper.get("initial_cash", "118.85"))),
        default_taker_fee=Decimal(str(paper.get("default_taker_fee", "0.004"))),
        market_slippage_bps=Decimal(str(paper.get("market_slippage_bps", "5"))),
        base_url=str(market_data.get("base_url", "https://api.kraken.com/0/public")),
        order_book_depth=int(market_data.get("order_book_depth", 25)),
        ohlcv_limit=int(market_data.get("ohlcv_limit", 200)),
        request_timeout_seconds=int(market_data.get("request_timeout_seconds", 15)),
    )
    if cfg.live_trading_enabled or not cfg.paper_only:
        raise ConfigurationError("Phase 1 is paper-only: live_trading_enabled must be false and paper_only true")
    if cfg.exchange.lower() != "kraken":
        raise ConfigurationError("Phase 1 is configured for the Kraken public adapter")
    if cfg.initial_cash < 0 or cfg.default_taker_fee < 0 or cfg.market_slippage_bps < 0:
        raise ConfigurationError("cash, fees, and slippage cannot be negative")
    return cfg

