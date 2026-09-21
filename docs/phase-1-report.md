# Phase 1 implementation report

## Delivered

- Exchange-neutral Decimal domain models and protocols.
- Read-only Kraken Spot REST adapter for AssetPairs, Ticker, OHLC, and Depth.
- Canonical market symbols, precision/minimum rules, fees, OHLCV, order books,
  bid/ask spreads, and normalized snapshots.
- Spot portfolio accounting with available/reserved cash, orders, fills,
  partial fills, positions, realized/unrealized P&L, and fees.
- Paper execution that walks order-book liquidity and does not assume every
  limit order fills immediately.
- SQLite persistence and structured JSON logging.
- TOML configuration with a fail-closed Phase 1 live-trading guard.
- Automated tests covering normalization, adapter parsing, accounting,
  partial fills, non-fills, persistence, and safety configuration.

## Evidence

Run from the repository root:

```text
python -m unittest discover -s tests -v
```

The CLI requires `--once` and uses only Kraken public market-data endpoints.

## Known limitations

- OHLC is limited by Kraken's public endpoint history window and the adapter
  intentionally returns the endpoint's rows without local backfill.
- The paper matcher models displayed aggregate book liquidity; it does not yet
  model queue priority, hidden liquidity, latency, or websocket book deltas.
- Fee schedules are parsed from Kraken's public pair metadata, with a
  conservative configured fallback when the endpoint omits them.
- The persistence layer currently stores state snapshots and events but does not
  yet provide crash-recovery replay or schema migrations.

## Decisions for ChatGPT

1. Choose the future strategy/risk-management interface and its approval gates.
2. Decide whether Phase 2 should use REST polling, Kraken WebSocket v2, or both
   for execution-quality simulation before any authenticated adapter is planned.
3. Define the required audit/replay guarantees and migration policy for the
   SQLite event store.
4. Define how fee tier selection and currency conversion should be handled for
   multi-quote portfolios.

