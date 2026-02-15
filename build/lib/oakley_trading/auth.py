"""Binance credential management — store and retrieve API keys."""

from __future__ import annotations

import json
from typing import Optional

from oakley_trading.common.config import Config


def _load_config() -> dict:
    """Load config from disk."""
    Config.ensure_dirs()
    if not Config.config_path.exists():
        return {}
    try:
        return json.loads(Config.config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config(data: dict) -> None:
    """Write config to disk."""
    Config.ensure_dirs()
    Config.config_path.write_text(json.dumps(data, indent=2))


def save_credentials(api_key: str, api_secret: str) -> None:
    """Save Binance API credentials to config file."""
    config = _load_config()
    config["api_key"] = api_key
    config["api_secret"] = api_secret
    _save_config(config)


def get_credentials() -> Optional[tuple[str, str]]:
    """Return (api_key, api_secret) or None if not configured."""
    config = _load_config()
    key = config.get("api_key")
    secret = config.get("api_secret")
    if key and secret:
        return (key, secret)
    return None


def has_credentials() -> bool:
    """Check if credentials are configured."""
    return get_credentials() is not None
