import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
import sqlite3

from autotrader.audit import AuditEvent
from autotrader.models import AssetRules, Market, Order, OrderSide, OrderType
from autotrader.persistence import SQLiteStore
from autotrader.portfolio import Portfolio


class PersistenceTests(unittest.TestCase):
    def test_schema_and_snapshot_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "state.sqlite3")
            market = Market("BTC/USD", "XXBTZUSD", "BTC", "USD", AssetRules())
            portfolio = Portfolio.with_cash("USD", Decimal("118.85"))
            order = Order("o1", market.symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("0.01"), Decimal("100"))
            store.record_order(order)
            store.record_event("test", {"ok": True})
            event = AuditEvent("risk_decision", {"approved": False})
            store.append(event)
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(event)
            store.snapshot(portfolio)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0], 1)
            store.close()
