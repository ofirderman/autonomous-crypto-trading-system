# Phase 2 implementation report

## Delivered

- Dynamic Kraken spot-market discovery using REST AssetPairs, ticker, order-book,
  and closed OHLCV data.
- Configurable filters for availability, quote volume, book depth, spread,
  history length, volatility measurement, and estimated round-trip cost.
- Configurable maker/taker fee tiers and a cost model covering spread, displayed
  book slippage, fees, entry/exit costs, and explicit conversion costs.
- Explicit timestamped conversion rates with inverse-rate support; USD remains
  the accounting currency.
- Strategy protocol, registry, evaluator, structured proposals, evidence fields,
  and confidence validation without invented probabilities.
- Independent risk engine covering exposure, position risk, concurrency, funds,
  minimums, fees, spread/slippage, stale data, duplicate orders, drawdown, and
  manual emergency shutdown.
- Append-only audit events for market eligibility, strategy evaluation, risk
  decisions, order submission/cancellation, and execution fills.
- Future websocket subscription/event interface without opening a websocket.
- Deterministic OHLCV checksum/splits and a look-ahead-safe backtesting engine
  with fees, slippage, stop-loss, target, and conservative same-bar handling.

## Verification

```text
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m autotrader --config config.example.toml --market BTC/USD --once
```

The suite covers Phase 1 behavior plus fee schedules, conversions, filtering,
structured proposals, risk rejection paths, audit events, websocket boundaries,
historical integrity, chronological splits, and stop-first execution.

## Known limitations

- Kraken market discovery is REST/polling only; websocket transport is a future
  interface, not an active implementation.
- Displayed order-book depth is not queue position, hidden liquidity, latency, or
  a guarantee of execution.
- Multi-quote valuation requires callers to provide current explicit conversion
  rates and marks for existing non-proposal positions.
- The backtester is a foundation, not a performance claim or optimizer. It does
  not model every exchange matching rule or corporate/asset event.
- Audit storage is append-only at the event table, but full crash-recovery replay
  and schema migration tooling remain future work.

## Architectural questions for ChatGPT

1. Which strategy families should receive dedicated Phase 3 research, and what
   evidence threshold is required before any strategy can be considered?
2. Should future continuous monitoring use Kraken WebSocket v2 only for updates,
   or retain REST reconciliation as a required source of truth?
3. What audit retention, replay, and schema-migration guarantees are required?
4. Should risk limits be globally configured or support per-market/per-asset
   overrides after more data-quality evidence exists?

Phase 3 was not started. Live trading remains disabled.
