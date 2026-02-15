"""Thin wrapper around python-binance for Binance REST API access."""

from __future__ import annotations

from typing import Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

from oakley_trading import auth
from oakley_trading.common.config import Config
from oakley_trading.common.rate_limiter import RateLimiter

_client: Optional[Client] = None
_limiter = RateLimiter()


def get_client() -> Client:
    """Get or create the Binance API client. Raises if no credentials."""
    global _client
    if _client is not None:
        return _client

    creds = auth.get_credentials()
    if creds is None:
        raise RuntimeError(
            "Binance credentials not configured. Run: oakley-trading setup --api-key KEY --api-secret SECRET"
        )

    api_key, api_secret = creds
    _client = Client(api_key, api_secret)
    return _client


def api_call(func, *args, **kwargs):
    """Execute a rate-limited Binance API call with timeout handling."""
    _limiter.acquire()
    try:
        return func(*args, **kwargs)
    except BinanceAPIException as e:
        raise RuntimeError(f"Binance API error {e.code}: {e.message}") from e
    except Exception as e:
        raise RuntimeError(f"Binance request failed: {e}") from e


def test_connection() -> dict:
    """Test Binance connection. Returns status dict."""
    try:
        client = get_client()
        status = api_call(client.get_system_status)
        server_time = api_call(client.get_server_time)
        return {
            "connected": True,
            "status": status.get("msg", "normal"),
            "server_time": server_time.get("serverTime"),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}
