import json
import unittest
from urllib.parse import parse_qs, urlparse

from autotrader.kraken import KrakenPublicAdapter


class KrakenTests(unittest.TestCase):
    def test_public_payloads_normalize_to_domain_models(self):
        calls = []
        payloads = {
            "AssetPairs": {"error": [], "result": {"XXBTZUSD": {"wsname": "XBT/USD", "base": "XXBT", "quote": "ZUSD", "pair_decimals": 1, "lot_decimals": 8, "tick_size": "0.1", "ordermin": "0.0001", "costmin": "0.5", "fees": [[0, 0.4]], "fees_maker": [[0, 0.25]], "status": "online"}}},
            "Ticker": {"error": [], "result": {"XXBTZUSD": {"b": ["100", "1", "1"], "a": ["101", "1", "1"], "c": ["100.5", "1"], "v": ["10", "20"]}}},
            "Depth": {"error": [], "result": {"XXBTZUSD": {"bids": [["100", "2", 1]], "asks": [["101", "1.5", 1]]}}},
            "OHLC": {"error": [], "result": {"XXBTZUSD": [[1700000000, "99", "102", "98", "101", "100", "12.5", 4], [1700000060, "101", "103", "100", "102", "101", "9.5", 3]], "last": 1700000060}},
        }

        def transport(url, timeout):
            endpoint = urlparse(url).path.rsplit("/", 1)[-1]
            calls.append((endpoint, parse_qs(urlparse(url).query)))
            return json.dumps(payloads[endpoint]).encode()

        adapter = KrakenPublicAdapter(transport=transport)
        market = adapter.list_markets()[0]
        self.assertEqual(market.symbol, "BTC/USD")
        self.assertEqual(str(market.rules.taker_fee), "0.004")
        self.assertEqual(adapter.fetch_ticker("BTC/USD").ask, 101)
        self.assertEqual(adapter.fetch_order_book("BTC/USD").best_bid, 100)
        candles = adapter.fetch_ohlcv("BTC/USD")
        self.assertEqual(candles[0].volume, 12.5)
        self.assertEqual(len(candles), 1)
        self.assertEqual({entry[0] for entry in calls}, {"AssetPairs", "Ticker", "Depth", "OHLC"})
