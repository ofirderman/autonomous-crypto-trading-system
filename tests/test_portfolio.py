import unittest
from decimal import Decimal

from autotrader.models import AssetRules, Fill, Market, Order, OrderSide, OrderType
from autotrader.portfolio import Portfolio


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.market = Market("BTC/USD", "XXBTZUSD", "BTC", "USD", AssetRules())
        self.portfolio = Portfolio.with_cash("USD", Decimal("118.85"))

    def test_available_reserved_realized_and_unrealized(self):
        buy = Order("buy", self.market.symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("1"), Decimal("100"))
        self.portfolio.register_order(buy, self.market, Decimal("100"), Decimal("0.01"))
        self.portfolio.apply_fill(Fill("f1", "buy", self.market.symbol, OrderSide.BUY, Decimal("1"), Decimal("100"), Decimal("1"), "USD"), self.market)
        self.portfolio.finalize_order("buy")
        self.assertEqual(self.portfolio.positions["BTC"].cost_basis, Decimal("101"))
        self.assertEqual(self.portfolio.unrealized_pnl({"BTC": Decimal("110")}), Decimal("9"))

        sell = Order("sell", self.market.symbol, OrderSide.SELL, OrderType.LIMIT, Decimal("0.5"), Decimal("120"))
        self.portfolio.register_order(sell, self.market, Decimal("120"), Decimal("0.01"))
        self.portfolio.apply_fill(Fill("f2", "sell", self.market.symbol, OrderSide.SELL, Decimal("0.5"), Decimal("120"), Decimal("0.6"), "USD"), self.market)
        self.portfolio.finalize_order("sell")
        self.assertEqual(self.portfolio.realized_pnl, Decimal("8.9"))
        self.assertEqual(self.portfolio.positions["BTC"].quantity, Decimal("0.5"))
