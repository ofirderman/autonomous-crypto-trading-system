"""Configuration loading with a fail-closed live-trading boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tomllib

from .costs import FeeSchedule, FeeTier
from .discovery import MarketDiscoveryConfig
from .risk import RiskConfig


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
    fee_schedule: FeeSchedule = FeeSchedule()
    discovery_config: MarketDiscoveryConfig = MarketDiscoveryConfig()
    risk_config: RiskConfig = RiskConfig()


def load_config(path: str | Path | None = None) -> AppConfig:
    raw: dict = {}
    if path is not None:
        config_path = Path(path)
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    system = raw.get("system", {})
    paper = raw.get("paper", {})
    market_data = raw.get("market_data", {})
    discovery = raw.get("discovery", {})
    risk = raw.get("risk", {})
    fee_config = raw.get("fees", {})
    configured_tiers = fee_config.get("tiers")
    if configured_tiers:
        tiers = tuple(FeeTier(Decimal(str(item.get("volume_threshold", "0"))), Decimal(str(item.get("maker", "0.004"))), Decimal(str(item.get("taker", "0.004")))) for item in configured_tiers)
    else:
        tiers = (FeeTier(Decimal("0"), Decimal(str(fee_config.get("default_maker", paper.get("default_taker_fee", "0.004")))), Decimal(str(fee_config.get("default_taker", paper.get("default_taker_fee", "0.004"))))),)
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
        fee_schedule=FeeSchedule(tiers),
        discovery_config=MarketDiscoveryConfig(
            min_volume_24h_quote=Decimal(str(discovery.get("min_volume_24h_quote", "0"))),
            min_depth_quote=Decimal(str(discovery.get("min_depth_quote", "0"))),
            max_spread_bps=Decimal(str(discovery.get("max_spread_bps", "100"))),
            max_round_trip_cost_bps=Decimal(str(discovery.get("max_round_trip_cost_bps", "250"))),
            min_ohlcv_rows=int(discovery.get("min_ohlcv_rows", 50)),
            sample_notional_quote=Decimal(str(discovery.get("sample_notional_quote", "10"))),
            require_online=bool(discovery.get("require_online", True)),
        ),
        risk_config=RiskConfig(
            accounting_currency=str(risk.get("accounting_currency", "USD")),
            initial_capital=Decimal(str(risk.get("initial_capital", paper.get("initial_cash", "118.85")))),
            max_gross_exposure_fraction=Decimal(str(risk.get("max_gross_exposure_fraction", "0.80"))),
            max_position_fraction=Decimal(str(risk.get("max_position_fraction", "0.25"))),
            max_position_risk_fraction=Decimal(str(risk.get("max_position_risk_fraction", "0.02"))),
            max_concurrent_positions=int(risk.get("max_concurrent_positions", 3)),
            max_spread_bps=Decimal(str(risk.get("max_spread_bps", "100"))),
            max_slippage_bps=Decimal(str(risk.get("max_slippage_bps", "100"))),
            stale_after=timedelta(seconds=int(risk.get("stale_after_seconds", 300))),
            max_drawdown_fraction=Decimal(str(risk.get("max_drawdown_fraction", "0.10"))),
            emergency_shutdown=bool(risk.get("emergency_shutdown", False)),
        ),
    )
    if cfg.live_trading_enabled or not cfg.paper_only:
        raise ConfigurationError("This release is paper-only: live_trading_enabled must be false and paper_only true")
    if cfg.exchange.lower() != "kraken":
        raise ConfigurationError("This release is configured for the Kraken public adapter")
    if cfg.initial_cash < 0 or cfg.default_taker_fee < 0 or cfg.market_slippage_bps < 0:
        raise ConfigurationError("cash, fees, and slippage cannot be negative")
    return cfg
