# Autonomous Crypto Trading System

Phase 1 foundation for a spot-only, exchange-independent cryptocurrency trading system.

The initial venue is Kraken Pro and the initial paper portfolio is configured with
`$118.85 USD`. Phase 1 contains no strategy, no credentials, no private exchange
API calls, and no live-order path. Market data is public; execution is paper-only.

## Quick start

Requirements: Python 3.11+.

```powershell
cd C:\Users\PC\Desktop\autonomous-crypto-trading-system
python -m unittest discover -s tests -v
python -m autotrader --config config.example.toml --market BTC/USD --once
```

The last command performs one public Kraken market-data collection and emits a
structured JSON snapshot. It does not place an order.

## Layout

- `src/autotrader/models.py` - exchange-neutral market, order, fill, and portfolio models.
- `src/autotrader/interfaces.py` - provider and execution protocols.
- `src/autotrader/kraken.py` - public Kraken REST adapter and normalization.
- `src/autotrader/market_data.py` - market-data collection and spread calculation.
- `src/autotrader/portfolio.py` - available/reserved funds, positions, P&L, and fees.
- `src/autotrader/paper.py` - order-book-aware paper execution with partial fills.
- `src/autotrader/persistence.py` - SQLite event and snapshot persistence.
- `src/autotrader/config.py` - TOML configuration with fail-closed live-trading guard.
- `docs/architecture.md` - Phase 1 boundaries and accounting invariants.
- `docs/phase-1-report.md` - implementation evidence and open architectural decisions.

## Safety boundary

`live_trading_enabled = true` is rejected by configuration loading. The Kraken
adapter implements only public market-data methods. Adding authenticated exchange
trading requires a later, explicit architectural decision and a separate phase.

