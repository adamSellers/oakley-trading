from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz

from .config import Config

_tz = pytz.timezone(Config.timezone)


def now_aedt() -> datetime:
    return datetime.now(_tz)


def format_datetime_aedt(dt: Optional[datetime] = None, fmt: str = "%d %b %Y %H:%M AEDT") -> str:
    if dt is None:
        dt = now_aedt()
    elif dt.tzinfo is None:
        dt = _tz.localize(dt)
    return dt.strftime(fmt)


def format_section_header(title: str) -> str:
    return f"**{title}**"


def format_list_item(text: str, indent: int = 0) -> str:
    prefix = "  " * indent
    return f"{prefix}- {text}"


def format_number(value: float, decimals: int = 2) -> str:
    """Format a number with comma separators."""
    if abs(value) >= 1:
        return f"{value:,.{decimals}f}"
    # For small numbers (crypto quantities), show more precision
    if abs(value) < 0.01:
        return f"{value:.6f}"
    return f"{value:.{decimals}f}"


def format_currency(value: float, symbol: str = "$") -> str:
    """Format as currency with sign for P&L."""
    if value >= 0:
        return f"{symbol}{format_number(value)}"
    return f"-{symbol}{format_number(abs(value))}"


def format_percent(value: float) -> str:
    """Format as percentage."""
    return f"{value:.1f}%"


def truncate_for_telegram(text: str, max_length: int = Config.telegram_max_length) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[: max_length - 30]
    last_newline = truncated.rfind("\n")
    if last_newline > max_length // 2:
        truncated = truncated[:last_newline]
    return truncated + "\n\n... (truncated)"
