"""Market data service — prices, candles, account info, exchange info, order execution."""

from __future__ import annotations

import math
from typing import Optional

from oakley_trading.client import get_client, api_call
from oakley_trading.common.cache import FileCache
from oakley_trading.common.config import Config

_cache = FileCache("market")
_exchange_info: dict[str, dict] = {}


def _load_exchange_info(symbol: Optional[str] = None) -> None:
    """Load LOT_SIZE and NOTIONAL filters from Binance exchange info."""
    global _exchange_info

    cache_key = "exchange_info"
    cached = _cache.get(cache_key, ttl=Config.cache_ttl["exchange_info"])
    if cached and not cached.get("_stale"):
        _exchange_info = cached
        if symbol is None or symbol in _exchange_info:
            return

    client = get_client()
    if symbol:
        data = api_call(client.get_symbol_info, symbol)
        if data:
            _parse_symbol_info(data)
            _cache.set(cache_key, _exchange_info)
    else:
        data = api_call(client.get_exchange_info)
        for s in data.get("symbols", []):
            _parse_symbol_info(s)
        _cache.set(cache_key, _exchange_info)


def _parse_symbol_info(symbol_data: dict) -> None:
    """Parse filters from a single symbol's exchange info."""
    sym = symbol_data["symbol"]
    filters = {}
    for f in symbol_data.get("filters", []):
        filters[f["filterType"]] = f

    _exchange_info[sym] = {
        "step_size": float(filters.get("LOT_SIZE", {}).get("stepSize", 0.00001)),
        "min_notional": float(filters.get("NOTIONAL", {}).get("minNotional", 10)),
        "min_qty": float(filters.get("LOT_SIZE", {}).get("minQty", 0.00001)),
    }


def get_exchange_info(symbol: str) -> dict:
    """Get exchange info for a symbol (step_size, min_notional)."""
    if symbol not in _exchange_info:
        _load_exchange_info(symbol)
    return _exchange_info.get(symbol, {
        "step_size": 0.00001,
        "min_notional": 10,
        "min_qty": 0.00001,
    })


def step_size(symbol: str, quantity: float) -> float:
    """Apply LOT_SIZE precision to a quantity. Floors to nearest step."""
    info = get_exchange_info(symbol)
    step = info["step_size"]
    if step <= 0:
        return round(quantity, 6)
    precision = max(0, int(round(-math.log10(step))))
    floored = math.floor(quantity / step) * step
    return round(floored, precision)


def get_price(symbol: str) -> Optional[dict]:
    """Get current price for a symbol. Returns {price, symbol} or None."""
    cache_key = f"price_{symbol}"
    cached = _cache.get(cache_key, ttl=Config.cache_ttl["price"])
    if cached:
        return cached

    try:
        client = get_client()
        ticker = api_call(client.get_symbol_ticker, symbol=symbol)
        result = {"symbol": symbol, "price": float(ticker["price"])}
        _cache.set(cache_key, result)
        return result
    except Exception:
        # Try stale cache
        stale = _cache.get(cache_key)
        if stale:
            return stale
        return None


def get_prices(symbols: Optional[list[str]] = None) -> list[dict]:
    """Get prices for multiple symbols. If None, returns all tracked."""
    try:
        client = get_client()
        if symbols:
            results = []
            for sym in symbols:
                price_data = get_price(sym)
                if price_data:
                    results.append(price_data)
            return results
        else:
            tickers = api_call(client.get_all_tickers)
            # Filter to USDT pairs only
            results = []
            for t in tickers:
                if t["symbol"].endswith("USDT"):
                    results.append({"symbol": t["symbol"], "price": float(t["price"])})
            return results
    except Exception:
        return []


def get_candles(symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
    """Get OHLCV candle data."""
    cache_key = f"candles_{symbol}_{interval}_{limit}"
    cached = _cache.get(cache_key, ttl=Config.cache_ttl["candles"])
    if cached:
        return cached

    try:
        client = get_client()
        raw = api_call(client.get_klines, symbol=symbol, interval=interval, limit=limit)
        candles = []
        for c in raw:
            candles.append({
                "open_time": c[0],
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "close_time": c[6],
            })
        _cache.set(cache_key, candles)
        return candles
    except Exception:
        stale = _cache.get(cache_key)
        return stale if stale else []


def get_account() -> dict:
    """Get account balances. Returns {balances: [...], error: None} or {error: str}."""
    cache_key = "account"
    cached = _cache.get(cache_key, ttl=Config.cache_ttl["account"])
    if cached and not cached.get("_stale"):
        return cached

    try:
        client = get_client()
        info = api_call(client.get_account)
        balances = []
        for b in info.get("balances", []):
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            if total > 0:
                balances.append({
                    "asset": b["asset"],
                    "free": free,
                    "locked": locked,
                    "total": total,
                })
        result = {"balances": balances, "error": None}
        _cache.set(cache_key, result)
        return result
    except Exception as e:
        stale = _cache.get(cache_key)
        if stale:
            return stale
        return {"balances": [], "error": str(e)}


def calculate_atr(symbol: str, period: int = 14, interval: str = "1d") -> Optional[float]:
    """Calculate Average True Range from candle data.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = SMA of True Range over `period` candles.

    Returns ATR value or None if insufficient data.
    """
    candles = get_candles(symbol, interval, limit=period + 1)
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    return sum(true_ranges[-period:]) / period


def execute_order(symbol: str, side: str, quantity: float) -> dict:
    """Execute a market order. Returns Binance order response."""
    client = get_client()
    formatted_qty = step_size(symbol, quantity)

    if formatted_qty <= 0:
        raise RuntimeError(f"Quantity too small after step_size adjustment: {quantity} -> {formatted_qty}")

    if side == "BUY":
        order = api_call(client.order_market_buy, symbol=symbol, quantity=formatted_qty)
    elif side == "SELL":
        order = api_call(client.order_market_sell, symbol=symbol, quantity=formatted_qty)
    else:
        raise ValueError(f"Invalid side: {side}. Must be BUY or SELL.")

    # Invalidate account cache after order
    _cache.clear("account")

    return order
