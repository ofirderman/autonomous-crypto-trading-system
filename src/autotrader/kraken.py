"""Read-only Kraken Spot REST market-data adapter.

Only public endpoints are used. The adapter never accepts API credentials and
never exposes a method that can submit, amend, or cancel an exchange order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import (
    AssetRules, Market, MarketSnapshot, OHLCV, OrderBook, OrderBookLevel, Ticker, dec,
)


class KrakenAPIError(RuntimeError):
    pass


class KrakenPublicAdapter:
    TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}

    def __init__(self, base_url: str = "https://api.kraken.com/0/public", timeout: int = 15,
                 transport: Callable[[str, int], bytes] | None = None, default_order_book_depth: int = 25):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_order_book_depth = default_order_book_depth
        self._transport = transport or self._default_transport
        self._markets: dict[str, Market] = {}

    @staticmethod
    def _default_transport(url: str, timeout: int) -> bytes:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "autonomous-crypto-trading-system/0.1"})
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    def _get(self, endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base_url}/{endpoint}"
        if query:
            url = f"{url}?{query}"
        try:
            payload = json.loads(self._transport(url, self.timeout).decode("utf-8"))
        except Exception as exc:
            raise KrakenAPIError(f"Kraken public request failed: {endpoint}: {exc}") from exc
        errors = payload.get("error", [])
        if errors:
            raise KrakenAPIError("; ".join(str(item) for item in errors))
        return payload.get("result", {})

    @staticmethod
    def _asset_name(value: str) -> str:
        aliases = {"XXBT": "BTC", "XBT": "BTC", "XDG": "DOGE", "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP", "ZCAD": "CAD"}
        return aliases.get(value.upper(), value.upper().lstrip("XZ"))

    @staticmethod
    def _pair_name(value: str) -> str:
        text = value.upper().replace("-", "/")
        if "/" in text:
            base, quote = text.split("/", 1)
            return f"{KrakenPublicAdapter._asset_name(base)}/{KrakenPublicAdapter._asset_name(quote)}"
        aliases = {"XBT": "BTC", "XXBT": "BTC", "USD": "USD", "ZUSD": "USD", "EUR": "EUR", "ZEUR": "EUR"}
        for quote in ("ZUSD", "USD", "ZEUR", "EUR", "ZGBP", "GBP", "XXBT", "XBT", "BTC"):
            if text.endswith(quote) and len(text) > len(quote):
                return f"{aliases.get(text[:-len(quote)], KrakenPublicAdapter._asset_name(text[:-len(quote)]))}/{aliases.get(quote, KrakenPublicAdapter._asset_name(quote))}"
        return text

    def list_markets(self) -> list[Market]:
        raw = self._get("AssetPairs", {"assetVersion": 1})
        markets: list[Market] = []
        for exchange_symbol, info in raw.items():
            if not isinstance(info, dict):
                continue
            symbol = self._pair_name(str(info.get("wsname") or info.get("altname") or exchange_symbol))
            base = self._asset_name(str(info.get("base", symbol.split("/")[0])))
            quote = self._asset_name(str(info.get("quote", symbol.split("/")[-1])))
            fees = info.get("fees") or []
            fees_maker = info.get("fees_maker") or fees
            taker_fee = self._fee_from_schedule(fees) or Decimal("0.004")
            maker_fee = self._fee_from_schedule(fees_maker) or taker_fee
            rules = AssetRules(
                price_increment=dec(info.get("tick_size") or (Decimal(1).scaleb(-int(info.get("pair_decimals", 8))))),
                quantity_increment=Decimal(1).scaleb(-int(info.get("lot_decimals", 8))),
                min_quantity=dec(info.get("ordermin") or 0),
                min_notional=dec(info.get("costmin") or 0),
                maker_fee=maker_fee,
                taker_fee=taker_fee,
                status=str(info.get("status", "online")),
            )
            market = Market(symbol, exchange_symbol, base, quote, rules)
            markets.append(market)
            self._markets[symbol] = market
        return markets

    @staticmethod
    def _fee_from_schedule(schedule: Any) -> Decimal | None:
        try:
            values = [dec(row[1]) / Decimal("100") for row in schedule if len(row) >= 2]
            return values[0] if values else None
        except (TypeError, ValueError, IndexError):
            return None

    def _market(self, symbol: str) -> Market:
        canonical = self._pair_name(symbol)
        if canonical not in self._markets:
            self.list_markets()
        try:
            return self._markets[canonical]
        except KeyError as exc:
            raise KrakenAPIError(f"Unknown Kraken spot market: {symbol}") from exc

    def _result_for_market(self, result: Mapping[str, Any], market: Market) -> Mapping[str, Any]:
        for key, value in result.items():
            if key == market.exchange_symbol or self._pair_name(str(key)) == market.symbol:
                return value
        if len(result) == 1:
            return next(iter(result.values()))
        raise KrakenAPIError(f"Kraken response did not contain market {market.symbol}")

    def fetch_ticker(self, symbol: str) -> Ticker:
        market = self._market(symbol)
        item = self._result_for_market(self._get("Ticker", {"pair": market.exchange_symbol}), market)
        return Ticker(market.symbol, dec(item["b"][0]), dec(item["a"][0]), dec(item["c"][0]), dec(item["v"][1]), datetime.now(timezone.utc))

    def fetch_order_book(self, symbol: str, depth: int = 25) -> OrderBook:
        market = self._market(symbol)
        item = self._result_for_market(self._get("Depth", {"pair": market.exchange_symbol, "count": depth}), market)
        bids = tuple(OrderBookLevel(dec(row[0]), dec(row[1])) for row in item.get("bids", []))
        asks = tuple(OrderBookLevel(dec(row[0]), dec(row[1])) for row in item.get("asks", []))
        return OrderBook(market.symbol, bids, asks, datetime.now(timezone.utc))

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> list[OHLCV]:
        if timeframe not in self.TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported Kraken timeframe: {timeframe}")
        market = self._market(symbol)
        result = self._get("OHLC", {"pair": market.exchange_symbol, "interval": self.TIMEFRAME_MINUTES[timeframe]})
        rows = self._result_for_market(result, market)
        # Kraken documents the final row as the current, not-yet-committed
        # timeframe. Keep only closed candles for normalized historical data.
        closed_rows = list(rows)[:-1] if rows else []
        values = closed_rows[: max(0, limit)]
        output: list[OHLCV] = []
        for row in values:
            output.append(OHLCV(datetime.fromtimestamp(int(row[0]), timezone.utc), dec(row[1]), dec(row[2]), dec(row[3]), dec(row[4]), dec(row[6]), dec(row[5]), int(row[7]), True))
        return output

    def fetch_snapshot(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> MarketSnapshot:
        market = self._market(symbol)
        return MarketSnapshot(market, self.fetch_ticker(market.symbol), self.fetch_order_book(market.symbol, self.default_order_book_depth), tuple(self.fetch_ohlcv(market.symbol, timeframe, limit)))
