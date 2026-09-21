"""SQLite persistence for orders, fills, events, and portfolio snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from .audit import AuditEvent
from .models import Fill, Order, Position
from .portfolio import Portfolio


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
            type TEXT NOT NULL, quantity TEXT NOT NULL, limit_price TEXT,
            filled_quantity TEXT NOT NULL, average_fill_price TEXT,
            status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY, order_id TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT NOT NULL,
            fee TEXT NOT NULL, fee_asset TEXT NOT NULL, timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            available TEXT NOT NULL, reserved TEXT NOT NULL, positions TEXT NOT NULL,
            realized_pnl TEXT NOT NULL, total_fees TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT NOT NULL
        );
        """)
        self.connection.commit()

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    def record_order(self, order: Order) -> None:
        self.connection.execute("""INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            order.id, order.symbol, order.side.value, order.type.value, str(order.quantity),
            str(order.limit_price) if order.limit_price is not None else None, str(order.filled_quantity),
            str(order.average_fill_price) if order.average_fill_price is not None else None,
            order.status.value, self._iso(order.created_at), self._iso(order.updated_at),
        ))
        self.connection.commit()

    def record_fill(self, fill: Fill) -> None:
        self.connection.execute("""INSERT OR REPLACE INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            fill.id, fill.order_id, fill.symbol, fill.side.value, str(fill.quantity), str(fill.price),
            str(fill.fee), fill.fee_asset, self._iso(fill.timestamp),
        ))
        self.connection.commit()

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO events(timestamp, event_type, payload) VALUES (?, ?, ?)", (self._iso(datetime.now(timezone.utc)), event_type, json.dumps(payload, default=str, sort_keys=True)))
        self.connection.commit()

    def append(self, event: AuditEvent) -> None:
        """Append an immutable audit event; no replace/update path is provided."""
        self.connection.execute("INSERT INTO audit_events(event_id, timestamp, event_type, payload) VALUES (?, ?, ?, ?)", (event.event_id, self._iso(event.timestamp), event.event_type, event.as_json()))
        self.connection.commit()

    def snapshot(self, portfolio: Portfolio) -> None:
        positions = {asset: {"quantity": str(p.quantity), "cost_basis": str(p.cost_basis)} for asset, p in portfolio.positions.items()}
        self.connection.execute("INSERT INTO portfolio_snapshots(timestamp, available, reserved, positions, realized_pnl, total_fees) VALUES (?, ?, ?, ?, ?, ?)", (
            self._iso(datetime.now(timezone.utc)), json.dumps({k: str(v) for k, v in portfolio.available.items()}, sort_keys=True),
            json.dumps({k: str(v) for k, v in portfolio.reserved.items()}, sort_keys=True), json.dumps(positions, sort_keys=True),
            str(portfolio.realized_pnl), str(portfolio.total_fees),
        ))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
