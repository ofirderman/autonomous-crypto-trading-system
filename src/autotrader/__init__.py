"""Phase 1 foundation for an exchange-independent spot trading system."""

from .models import (
    AssetRules,
    Fill,
    Market,
    MarketSnapshot,
    OHLCV,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Ticker,
)
from .costs import CostModel, FeeSchedule, FeeTier
from .conversion import ConversionRate, ConversionRates
from .discovery import MarketDiscovery, MarketDiscoveryConfig
from .risk import RiskConfig, RiskDecision, RiskEngine
from .strategy import Direction, StrategyEvaluator, StrategyRegistry, TradeProposal

__all__ = [
    "AssetRules", "Fill", "Market", "MarketSnapshot", "OHLCV", "Order",
    "OrderBook", "OrderBookLevel", "OrderSide", "OrderStatus", "OrderType",
    "Position", "Ticker",
    "CostModel", "FeeSchedule", "FeeTier", "ConversionRate", "ConversionRates",
    "MarketDiscovery", "MarketDiscoveryConfig", "RiskConfig", "RiskDecision", "RiskEngine",
    "Direction", "StrategyEvaluator", "StrategyRegistry", "TradeProposal",
]
