import unittest
from decimal import Decimal
from datetime import datetime, timezone

from autotrader.models import AssetRules, Market, MarketSnapshot, OrderBook, OrderBookLevel, OrderSide, OrderType, Ticker
from autotrader.paper import ExecutionConfig, PaperExecutionEngine, PaperExecutionError
from autotrader.portfolio import Portfolio


def market():
    return Market("BTC/USD", "XXBTZUSD", "BTC", "USD", AssetRules(price_increment=Decimal("0.01"), quantity_increment=Decimal("0.01"), min_quantity=Decimal("0.01"), min_notional=Decimal("1"), maker_fee=Decimal("0.001"), taker_fee=Decimal("0.002")))


def snapshot(book):
    m = market()
    ticker = Ticker(m.symbol, book.best_bid, book.best_ask, book.midpoint, Decimal("10"), datetime.now(timezone.utc))
    return MarketSnapshot(m, ticker, book)


class PaperTests(unittest.TestCase):
    def test_limit_order_waits_then_partially_fills_from_book(self):
        m = market()
        portfolio = Portfolio.with_cash("USD", Decimal("118.85"))
        engine = PaperExecutionEngine({m.symbol: m}, portfolio)
        order = engine.submit_order(m.symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("1.00"), limit_price=Decimal("100"))
        no_fill_book = OrderBook(m.symbol, (OrderBookLevel(Decimal("99"), Decimal("2")),), (OrderBookLevel(Decimal("101"), Decimal("2")),), datetime.now(timezone.utc))
        self.assertEqual(engine.process_snapshot(snapshot(no_fill_book)), ())
        fill_book = OrderBook(m.symbol, (OrderBookLevel(Decimal("99"), Decimal("2")),), (OrderBookLevel(Decimal("100"), Decimal("0.40")),), datetime.now(timezone.utc))
        fills = engine.process_snapshot(snapshot(fill_book))
        self.assertEqual(fills[0].quantity, Decimal("0.40"))
        self.assertEqual(order.status.value, "partially_filled")
        self.assertEqual(portfolio.positions["BTC"].quantity, Decimal("0.40"))
        self.assertGreater(portfolio.free("USD"), Decimal("0"))
        self.assertGreater(portfolio.reserved["USD"], Decimal("0"))

    def test_sell_cannot_exceed_owned_position(self):
        m = market()
        engine = PaperExecutionEngine({m.symbol: m}, Portfolio.with_cash("USD", Decimal("118.85")))
        with self.assertRaises(PaperExecutionError):
            engine.submit_order(m.symbol, OrderSide.SELL, OrderType.LIMIT, Decimal("0.01"), limit_price=Decimal("100"))

    def test_market_order_walks_multiple_levels_and_charges_fee(self):
        m = market()
        portfolio = Portfolio.with_cash("USD", Decimal("118.85"))
        engine = PaperExecutionEngine({m.symbol: m}, portfolio, ExecutionConfig(Decimal("0.002"), Decimal("0")))
        order = engine.submit_order(m.symbol, OrderSide.BUY, OrderType.MARKET, Decimal("1.00"), reference_price=Decimal("100"))
        book = OrderBook(m.symbol, (OrderBookLevel(Decimal("99"), Decimal("1")),), (OrderBookLevel(Decimal("100"), Decimal("0.50")), OrderBookLevel(Decimal("101"), Decimal("0.50"))), datetime.now(timezone.utc))
        fills = engine.process_snapshot(snapshot(book))
        self.assertEqual(sum(fill.quantity for fill in fills), Decimal("1.00"))
        self.assertEqual(order.status.value, "filled")
        self.assertGreater(portfolio.total_fees, Decimal("0"))
        self.assertEqual(portfolio.positions["BTC"].quantity, Decimal("1.00"))

