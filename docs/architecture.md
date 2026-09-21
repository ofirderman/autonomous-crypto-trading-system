# Phase 1 architecture

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

There is no strategy, signal ranking, risk policy, scheduler, authenticated
Kraken client, withdrawal/funding operation, or live execution path. Those are
later architectural decisions and must not be inferred from Phase 1.

