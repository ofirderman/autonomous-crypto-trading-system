"""Explicit, timestamped currency conversion rates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .models import ZERO, dec


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class ConversionRate:
    from_asset: str
    to_asset: str
    rate: Decimal
    timestamp: datetime
    cost_bps: Decimal = ZERO

    def __post_init__(self) -> None:
        if self.rate <= ZERO or self.cost_bps < ZERO:
            raise ConversionError("conversion rate must be positive and conversion cost non-negative")


class ConversionRates:
    def __init__(self, rates: list[ConversionRate] | tuple[ConversionRate, ...] = ()):
        self._rates: dict[tuple[str, str], ConversionRate] = {}
        for rate in rates:
            self.add(rate)

    def add(self, rate: ConversionRate) -> None:
        self._rates[(rate.from_asset.upper(), rate.to_asset.upper())] = rate

    def get(self, from_asset: str, to_asset: str) -> ConversionRate | None:
        if from_asset.upper() == to_asset.upper():
            return ConversionRate(from_asset.upper(), to_asset.upper(), Decimal("1"), datetime.now(timezone.utc))
        direct = self._rates.get((from_asset.upper(), to_asset.upper()))
        if direct:
            return direct
        inverse = self._rates.get((to_asset.upper(), from_asset.upper()))
        if inverse:
            return ConversionRate(from_asset.upper(), to_asset.upper(), Decimal("1") / inverse.rate, inverse.timestamp, inverse.cost_bps)
        return None

    def convert(self, amount: Decimal, from_asset: str, to_asset: str) -> Decimal:
        rate = self.get(from_asset, to_asset)
        if rate is None:
            raise ConversionError(f"no explicit conversion rate for {from_asset}/{to_asset}")
        return dec(amount) * rate.rate

    def cost(self, amount: Decimal, from_asset: str, to_asset: str) -> Decimal:
        rate = self.get(from_asset, to_asset)
        if rate is None:
            raise ConversionError(f"no explicit conversion rate for {from_asset}/{to_asset}")
        return dec(amount) * rate.rate * rate.cost_bps / Decimal("10000")

