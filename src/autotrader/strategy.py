"""Strategy registration and proposal evaluation, independent of risk/execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, Sequence

from .audit import AuditTrail, record
from .models import MarketSnapshot, ZERO


class Direction(StrEnum):
    LONG = "long"


@dataclass(frozen=True)
class Evidence:
    name: str
    value: str
    source: str


@dataclass(frozen=True)
class TradeProposal:
    strategy_name: str
    symbol: str
    direction: Direction
    entry_conditions: tuple[str, ...]
    proposed_position_size: Decimal
    invalidation_condition: str
    stop_loss: Decimal
    profit_targets: tuple[Decimal, ...]
    estimated_holding_horizon: timedelta | None
    supporting_evidence: tuple[Evidence, ...]
    confidence: Decimal | None = None
    confidence_basis: str | None = None

    def validate(self, entry_reference: Decimal) -> None:
        if self.direction is not Direction.LONG:
            raise ValueError("spot Phase 2 supports long proposals only")
        if self.proposed_position_size <= ZERO or self.stop_loss <= ZERO:
            raise ValueError("proposal size and stop loss must be positive")
        if entry_reference <= self.stop_loss:
            raise ValueError("long stop loss must be below entry reference")
        if any(target <= entry_reference for target in self.profit_targets):
            raise ValueError("long profit targets must be above entry reference")
        if self.confidence is not None:
            if self.confidence_basis is None or not ZERO <= self.confidence <= Decimal("1"):
                raise ValueError("confidence requires a justified score between 0 and 1")


class Strategy(Protocol):
    name: str

    def evaluate(self, snapshot: MarketSnapshot) -> Sequence[TradeProposal]: ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        if not strategy.name or strategy.name in self._strategies:
            raise ValueError(f"strategy name is missing or already registered: {strategy.name}")
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> Strategy:
        return self._strategies[name]

    def all(self) -> tuple[Strategy, ...]:
        return tuple(self._strategies.values())


class StrategyEvaluator:
    def __init__(self, registry: StrategyRegistry, audit: AuditTrail | None = None):
        self.registry = registry
        self.audit = audit

    def evaluate(self, snapshot: MarketSnapshot) -> tuple[TradeProposal, ...]:
        proposals: list[TradeProposal] = []
        for strategy in self.registry.all():
            try:
                candidate_proposals = tuple(strategy.evaluate(snapshot))
                for proposal in candidate_proposals:
                    proposal.validate(snapshot.ticker.ask)
                    proposals.append(proposal)
                record(self.audit, "strategy_evaluation", {"strategy": strategy.name, "symbol": snapshot.market.symbol, "proposal_count": len(candidate_proposals), "status": "ok"})
            except Exception as exc:
                record(self.audit, "strategy_evaluation", {"strategy": strategy.name, "symbol": snapshot.market.symbol, "proposal_count": 0, "status": "error", "error": type(exc).__name__})
        return tuple(proposals)


class NoOpStrategy:
    """Explicit placeholder: it produces no proposals and makes no profitability claim."""

    name = "no-op"

    def evaluate(self, snapshot: MarketSnapshot) -> Sequence[TradeProposal]:
        return ()

