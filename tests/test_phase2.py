import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from autotrader.audit import InMemoryAuditTrail
from autotrader.backtest import BacktestEngine, BacktestSignal, HistoricalDataError, HistoricalDataPipeline
from autotrader.config import load_config
from autotrader.conversion import ConversionRate, ConversionRates, ConversionError
from autotrader.costs import CostModel, FeeSchedule, FeeTier
from autotrader.discovery import MarketDiscovery, MarketDiscoveryConfig
from autotrader.models import AssetRules, Market, MarketSnapshot, OHLCV, Order, OrderBook, OrderBookLevel, OrderSide, OrderStatus, OrderType, Ticker
from autotrader.paper import PaperExecutionEngine
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskConfig, RiskEngine
from autotrader.strategy import Direction, Evidence, StrategyEvaluator, StrategyRegistry, TradeProposal
from autotrader.websocket import KrakenWebSocketV2Interface


NOW = datetime.now(timezone.utc)


def make_market(symbol="BTC/USD", status="online"):
    base, quote = symbol.split("/")
    return Market(symbol, symbol.replace("/", ""), base, quote, AssetRules(price_increment=Decimal("0.01"), quantity_increment=Decimal("0.01"), min_quantity=Decimal("0.01"), min_notional=Decimal("1"), maker_fee=Decimal("0.001"), taker_fee=Decimal("0.002"), status=status))


def make_snapshot(market=None, bid="99.90", ask="100.10", candles=60, collected_at=NOW):
    market = market or make_market()
    book = OrderBook(market.symbol, (OrderBookLevel(Decimal(bid), Decimal("10")),), (OrderBookLevel(Decimal(ask), Decimal("10")),), collected_at)
    ticker = Ticker(market.symbol, Decimal(bid), Decimal(ask), Decimal(ask), Decimal("100"), collected_at)
    history = tuple(OHLCV(NOW - timedelta(hours=index), Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100"), Decimal("10")) for index in range(candles, 0, -1))
    return MarketSnapshot(market, ticker, book, history, collected_at)


class Phase2Tests(unittest.TestCase):
    def test_fee_schedule_and_round_trip_costs_are_fee_aware(self):
        schedule = FeeSchedule((FeeTier(Decimal("0"), Decimal("0.004"), Decimal("0.005")), FeeTier(Decimal("1000"), Decimal("0.002"), Decimal("0.003"))))
        self.assertEqual(schedule.rate(False, Decimal("1200")), Decimal("0.003"))
        snapshot = make_snapshot()
        estimate = CostModel(schedule, Decimal("5")).estimate_round_trip(snapshot.market, snapshot.order_book, Decimal("0.1"), Decimal("110"))
        self.assertGreater(estimate.total_cost, Decimal("0"))
        self.assertLess(estimate.net_pnl, estimate.gross_pnl)

    def test_phase2_configuration_loads_risk_discovery_and_fee_tiers(self):
        config = load_config("config.example.toml")
        self.assertEqual(config.risk_config.accounting_currency, "USD")
        self.assertEqual(config.risk_config.initial_capital, Decimal("118.85"))
        self.assertEqual(config.discovery_config.min_ohlcv_rows, 50)
        self.assertEqual(config.fee_schedule.rate(False), Decimal("0.004"))

    def test_explicit_conversion_rates_reject_missing_pairs(self):
        rates = ConversionRates([ConversionRate("EUR", "USD", Decimal("1.1"), NOW, Decimal("10"))])
        self.assertEqual(rates.convert(Decimal("10"), "EUR", "USD"), Decimal("11.0"))
        with self.assertRaises(ConversionError):
            rates.convert(Decimal("10"), "GBP", "USD")

    def test_market_discovery_filters_execution_quality_not_recent_gainers(self):
        snapshot = make_snapshot()
        discovery = MarketDiscovery(MarketDiscoveryConfig(min_volume_24h_quote=Decimal("1000"), min_depth_quote=Decimal("100"), max_spread_bps=Decimal("50"), max_round_trip_cost_bps=Decimal("500"), min_ohlcv_rows=2))
        result = discovery.evaluate(snapshot)
        self.assertTrue(result.eligible)
        self.assertIsNotNone(result.metrics.volatility_bps)
        wide = make_snapshot(bid="90", ask="110")
        rejected = discovery.evaluate(wide)
        self.assertFalse(rejected.eligible)
        self.assertIn("spread_too_wide", rejected.reasons)

    def test_strategy_registry_produces_structured_proposals_without_fake_confidence(self):
        class Strategy:
            name = "test-strategy"

            def evaluate(self, snapshot):
                return (TradeProposal(self.name, snapshot.market.symbol, Direction.LONG, ("test condition",), Decimal("0.1"), "condition invalidated", Decimal("95"), (Decimal("105"),), timedelta(hours=4), (Evidence("spread", "20 bps", "test"),)),)

        registry = StrategyRegistry()
        registry.register(Strategy())
        proposals = StrategyEvaluator(registry).evaluate(make_snapshot())
        self.assertEqual(len(proposals), 1)
        self.assertIsNone(proposals[0].confidence)

    def test_risk_engine_enforces_stale_data_duplicate_orders_and_shutdown(self):
        audit = InMemoryAuditTrail()
        proposal = TradeProposal("test", "BTC/USD", Direction.LONG, ("condition",), Decimal("0.1"), "invalid", Decimal("95"), (Decimal("105"),), None, ())
        portfolio = Portfolio.with_cash("USD", Decimal("118.85"))
        snapshot = make_snapshot()
        engine = RiskEngine(RiskConfig(max_spread_bps=Decimal("50"), max_slippage_bps=Decimal("50")), audit=audit)
        approved = engine.approve(proposal, snapshot, portfolio)
        self.assertTrue(approved.approved, approved.reasons)
        stale = make_snapshot(collected_at=NOW - timedelta(minutes=10))
        stale_decision = engine.approve(proposal, stale, portfolio)
        self.assertIn("stale_market_data", stale_decision.reasons)
        order = Order("duplicate", "BTC/USD", OrderSide.BUY, OrderType.LIMIT, Decimal("0.1"), Decimal("100"))
        portfolio.register_order(order, snapshot.market, Decimal("100"), Decimal("0.002"))
        duplicate = engine.approve(proposal, snapshot, portfolio)
        self.assertIn("duplicate_order", duplicate.reasons)
        engine.halt("operator")
        halted = engine.approve(proposal, snapshot, portfolio)
        self.assertIn("emergency_shutdown", halted.reasons)
        self.assertTrue(any(event.event_type == "risk_decision" for event in audit.events))

    def test_risk_engine_rejects_insufficient_funds_and_invalid_market(self):
        proposal = TradeProposal("test", "BTC/USD", Direction.LONG, ("condition",), Decimal("2"), "invalid", Decimal("95"), (Decimal("105"),), None, ())
        snapshot = make_snapshot()
        decision = RiskEngine().approve(proposal, snapshot, Portfolio.with_cash("USD", Decimal("1")))
        self.assertIn("insufficient_available_balance", decision.reasons)
        engine = PaperExecutionEngine({snapshot.market.symbol: snapshot.market}, Portfolio.with_cash("USD", Decimal("118.85")))
        with self.assertRaises(ValueError):
            engine.submit_order("NOPE/USD", OrderSide.BUY, OrderType.LIMIT, Decimal("0.1"), Decimal("100"))

    def test_risk_engine_enforces_position_limits_and_explicit_quote_conversion(self):
        market = make_market("BTC/EUR")
        snapshot = make_snapshot(market)
        proposal = TradeProposal("test", market.symbol, Direction.LONG, ("condition",), Decimal("2"), "invalid", Decimal("95"), (Decimal("105"),), None, ())
        portfolio = Portfolio(available={"USD": Decimal("118.85"), "EUR": Decimal("1000")}, reserved={"USD": Decimal("0"), "EUR": Decimal("0")})
        rates = ConversionRates([ConversionRate("EUR", "USD", Decimal("1.1"), NOW)])
        decision = RiskEngine(RiskConfig(max_position_fraction=Decimal("0.1"))).approve(proposal, snapshot, portfolio, rates)
        self.assertIn("maximum_position_exposure", decision.reasons)

    def test_backtest_splits_chronologically_and_stop_wins_same_bar(self):
        candles = tuple(OHLCV(NOW + timedelta(hours=i), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10")) for i in range(10))
        candles = candles[:2] + (OHLCV(NOW + timedelta(hours=2), Decimal("100"), Decimal("110"), Decimal("90"), Decimal("100"), Decimal("10")),) + candles[3:]
        dataset = HistoricalDataPipeline.from_ohlcv("BTC/USD", candles, "fixture")
        split = HistoricalDataPipeline.split(dataset)
        self.assertEqual(len(split.train.candles) + len(split.validation.candles) + len(split.out_of_sample.candles), 10)

        class Strategy:
            def propose(self, history):
                return BacktestSignal(Decimal("0.1"), Decimal("95"), Decimal("105")) if history else None

        result = BacktestEngine(slippage_bps=Decimal("0"), fee_schedule=FeeSchedule((FeeTier(Decimal("0"), Decimal("0"), Decimal("0")),))).run(dataset, Strategy())
        self.assertTrue(result.trades)
        self.assertEqual(result.trades[0].reason, "stop_loss")
        self.assertEqual(result.dataset_checksum, dataset.checksum)

    def test_historical_integrity_rejects_unclosed_or_invalid_candles(self):
        with self.assertRaises(HistoricalDataError):
            HistoricalDataPipeline.from_ohlcv("BTC/USD", [OHLCV(NOW, Decimal("100"), Decimal("99"), Decimal("98"), Decimal("99"), Decimal("1"))])

    def test_audit_trail_is_append_only_and_paper_execution_records_fills(self):
        audit = InMemoryAuditTrail()
        market = make_market()
        portfolio = Portfolio.with_cash("USD", Decimal("118.85"))
        engine = PaperExecutionEngine({market.symbol: market}, portfolio, audit=audit)
        order = engine.submit_order(market.symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("0.1"), Decimal("100.1"))
        engine.process_snapshot(make_snapshot())
        self.assertTrue(any(event.event_type == "order_submitted" for event in audit.events))
        self.assertTrue(any(event.event_type == "execution_fill" for event in audit.events))
        event_ids = [event.event_id for event in audit.events]
        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_websocket_boundary_only_builds_subscription_and_does_not_connect(self):
        stream = KrakenWebSocketV2Interface()
        stream.subscribe(("ticker", "book"), ("BTC/USD",), lambda event: None)
        self.assertEqual(stream.subscriptions[0]["method"], "subscribe")
        with self.assertRaises(NotImplementedError):
            stream.connect()
