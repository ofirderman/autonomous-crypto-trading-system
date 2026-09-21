"""Reproducible, chronology-preserving OHLCV backtesting foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
from pathlib import Path
from typing import Protocol, Sequence

from .costs import FeeSchedule
from .models import OHLCV, ZERO, dec


class HistoricalDataError(ValueError):
    pass


@dataclass(frozen=True)
class HistoricalDataSet:
    symbol: str
    candles: tuple[OHLCV, ...]
    source: str
    checksum: str

    def __post_init__(self) -> None:
        if not self.candles:
            raise HistoricalDataError("historical dataset cannot be empty")
        previous = None
        for candle in self.candles:
            if not candle.is_closed or candle.high < candle.low or candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.volume < ZERO:
                raise HistoricalDataError("historical candle violates OHLCV integrity")
            if previous is not None and candle.timestamp <= previous:
                raise HistoricalDataError("historical timestamps must be strictly increasing")
            previous = candle.timestamp


@dataclass(frozen=True)
class TemporalSplit:
    train: HistoricalDataSet
    validation: HistoricalDataSet
    out_of_sample: HistoricalDataSet


class HistoricalDataPipeline:
    @staticmethod
    def from_ohlcv(symbol: str, candles: Sequence[OHLCV], source: str = "memory") -> HistoricalDataSet:
        ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
        canonical = "\n".join("|".join(str(value) for value in (c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume)) for c in ordered)
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return HistoricalDataSet(symbol, ordered, source, checksum)

    @staticmethod
    def from_csv(path: str | Path, symbol: str) -> HistoricalDataSet:
        candles: list[OHLCV] = []
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                raw_timestamp = row["timestamp"]
                timestamp = datetime.fromtimestamp(int(raw_timestamp) / 1000, timezone.utc) if raw_timestamp.isdigit() else datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
                candles.append(OHLCV(timestamp, dec(row["open"]), dec(row["high"]), dec(row["low"]), dec(row["close"]), dec(row["volume"]), dec(row["vwap"]) if row.get("vwap") else None, int(row["trade_count"]) if row.get("trade_count") else None, row.get("is_closed", "true").lower() == "true"))
        return HistoricalDataPipeline.from_ohlcv(symbol, candles, str(path))

    @staticmethod
    def split(dataset: HistoricalDataSet, train_fraction: Decimal = Decimal("0.60"), validation_fraction: Decimal = Decimal("0.20")) -> TemporalSplit:
        if train_fraction <= ZERO or validation_fraction <= ZERO or train_fraction + validation_fraction >= Decimal("1"):
            raise HistoricalDataError("train and validation fractions must leave an out-of-sample segment")
        total = len(dataset.candles)
        train_end = max(1, int(total * train_fraction))
        validation_end = max(train_end + 1, int(total * (train_fraction + validation_fraction)))
        validation_end = min(validation_end, total - 1)
        return TemporalSplit(
            HistoricalDataPipeline.from_ohlcv(dataset.symbol, dataset.candles[:train_end], dataset.source),
            HistoricalDataPipeline.from_ohlcv(dataset.symbol, dataset.candles[train_end:validation_end], dataset.source),
            HistoricalDataPipeline.from_ohlcv(dataset.symbol, dataset.candles[validation_end:], dataset.source),
        )


@dataclass(frozen=True)
class BacktestSignal:
    quantity: Decimal
    stop_loss: Decimal
    profit_target: Decimal | None = None


class HistoricalStrategy(Protocol):
    def propose(self, history: Sequence[OHLCV]) -> BacktestSignal | None: ...


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    entry_time: datetime
    entry_price: Decimal
    exit_time: datetime
    exit_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    reason: str

    @property
    def net_pnl(self) -> Decimal:
        return (self.exit_price - self.entry_price) * self.quantity - self.entry_fee - self.exit_fee


@dataclass(frozen=True)
class BacktestResult:
    dataset_checksum: str
    trades: tuple[BacktestTrade, ...]
    ending_cash: Decimal
    forced_close: bool


class BacktestEngine:
    def __init__(self, initial_cash: Decimal = Decimal("118.85"), fee_schedule: FeeSchedule | None = None, slippage_bps: Decimal = Decimal("5")):
        self.initial_cash = dec(initial_cash)
        self.fee_schedule = fee_schedule or FeeSchedule()
        self.slippage_bps = dec(slippage_bps)

    def run(self, dataset: HistoricalDataSet, strategy: HistoricalStrategy) -> BacktestResult:
        cash = self.initial_cash
        position: tuple[BacktestSignal, datetime, Decimal, Decimal, Decimal] | None = None
        trades: list[BacktestTrade] = []
        fee_rate = self.fee_schedule.rate(False)
        for index, bar in enumerate(dataset.candles):
            if position is not None:
                signal, entry_time, entry_price, entry_fee, quantity = position
                stop_hit = bar.low <= signal.stop_loss
                target_hit = signal.profit_target is not None and bar.high >= signal.profit_target
                if stop_hit or target_hit:
                    reason = "stop_loss" if stop_hit else "profit_target"
                    raw_exit = signal.stop_loss if stop_hit else signal.profit_target
                    exit_price = raw_exit * (Decimal("1") - self.slippage_bps / Decimal("10000"))
                    exit_fee = raw_exit * quantity * fee_rate
                    cash += exit_price * quantity - exit_fee
                    trades.append(BacktestTrade(dataset.symbol, entry_time, entry_price, bar.timestamp, exit_price, quantity, entry_fee, exit_fee, reason))
                    position = None
            if position is None and index < len(dataset.candles) - 1:
                # The strategy sees only bars strictly before the execution bar.
                history = dataset.candles[:index]
                signal = strategy.propose(history)
                if signal is None or signal.quantity <= ZERO or signal.stop_loss <= ZERO:
                    continue
                entry_price = bar.open * (Decimal("1") + self.slippage_bps / Decimal("10000"))
                entry_fee = entry_price * signal.quantity * fee_rate
                required = entry_price * signal.quantity + entry_fee
                if required > cash or signal.stop_loss >= entry_price:
                    continue
                cash -= required
                position = (signal, bar.timestamp, entry_price, entry_fee, signal.quantity)
        forced_close = position is not None
        if position is not None:
            signal, entry_time, entry_price, entry_fee, quantity = position
            bar = dataset.candles[-1]
            exit_price = bar.close * (Decimal("1") - self.slippage_bps / Decimal("10000"))
            exit_fee = exit_price * quantity * fee_rate
            cash += exit_price * quantity - exit_fee
            trades.append(BacktestTrade(dataset.symbol, entry_time, entry_price, bar.timestamp, exit_price, quantity, entry_fee, exit_fee, "end_of_sample"))
        return BacktestResult(dataset.checksum, tuple(trades), cash, forced_close)

