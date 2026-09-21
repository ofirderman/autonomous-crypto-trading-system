# Phase 1-2 architecture

## Boundaries

The domain layer does not know Kraken field names. `MarketDataProvider` is the
read-only exchange boundary; an exchange adapter normalizes market identifiers,
precision rules, minimums, fee schedules, tickers, OHLCV, and order books into
the domain models. A future exchange adapter can implement the same protocol.

The execution boundary is paper-only in this phase. `PaperExecutionEngine`
matches against current bid/ask levels, walks multiple levels, charges fees,
allows partial fills, leaves limit orders open when their price is not reached,
and releases reservations on completion or cancellation.

## Accounting invariants

- `available[asset] + reserved[asset]` is the total wallet balance.
- Buy orders reserve quote currency; sell orders reserve owned base currency.
- A sell cannot create a negative base position.
- Fees are recorded explicitly and included in buy cost basis or sell proceeds.
- Realized P&L is updated only when inventory is sold.
- Unrealized P&L is mark-to-market and never changes cost basis.
- No margin, borrowing, derivatives, shorting, or forced position expiry exists.

## Persistence

SQLite stores orders, fills, structured event payloads, and portfolio snapshots.
The schema is intentionally append-friendly for later replay/audit work.

## Explicit exclusions

There is no production strategy selection, profitability claim, optimizer,
scheduler, authenticated Kraken client, withdrawal/funding operation, or live
execution path. The strategy and risk modules are interfaces and safety
foundations only; trading philosophy and production strategy selection remain
later architectural decisions.

## Phase 2 market intelligence

REST remains the initial transport for dynamic AssetPairs discovery and historical
OHLCV. `MarketDiscovery` evaluates each market using availability, quote volume,
displayed order-book depth, spread, volatility, history length, and estimated
round-trip execution cost. It does not rank or select markets solely by recent
price gain.

`websocket.py` defines a future event/subscription boundary for continuous ticker,
book, and OHLC monitoring. Its Kraken interface intentionally raises on connect
in this phase; no continuous network process is enabled.

## Strategy and risk separation

Strategies emit validated `TradeProposal` objects only. The proposal includes
entry conditions, size, invalidation, stop, targets, horizon, evidence, and an
optional confidence score that must have an explicit basis. The registry/evaluator
does not claim profitability or invent confidence probabilities.

`RiskEngine` independently rejects stale data, invalid spot direction, wide
spreads, excessive slippage, duplicate orders, insufficient funds, minimum-size
violations, exposure/risk/concurrency limits, drawdown breaches, and emergency
shutdown state. Execution remains a separate paper venue.

## Currency and cost policy

USD is the initial accounting currency. Non-USD quote assets require explicit
timestamped `ConversionRate` objects; missing conversions fail closed. Fee tiers,
spread, slippage, entry/exit fees, and conversion costs are included in discovery,
risk, and backtesting calculations. Withdrawals are not included in per-trade
costs.

## Backtesting policy

Historical candles are validated, checksummed, and split chronologically into
train, validation, and out-of-sample segments. A backtest strategy receives only
history strictly before the execution bar. Entry uses the next bar's open with
configured slippage and fees; when a bar touches both stop and target, stop-loss
fills first as a conservative assumption.
