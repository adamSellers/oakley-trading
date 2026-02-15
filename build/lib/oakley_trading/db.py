"""SQLite database — schema, trade CRUD, config CRUD, recovery queue."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from oakley_trading.common.config import Config

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    """Get or create a SQLite connection with WAL mode."""
    global _conn
    if _conn is not None:
        return _conn

    Config.ensure_dirs()
    _conn = sqlite3.connect(str(Config.db_path), timeout=10)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id            TEXT UNIQUE NOT NULL,
            symbol              TEXT NOT NULL,
            side                TEXT NOT NULL,
            direction           TEXT NOT NULL DEFAULT 'LONG',
            quantity            REAL NOT NULL,
            price               REAL NOT NULL,
            entry_price         REAL,
            exit_price          REAL,
            total_value         REAL NOT NULL DEFAULT 0,
            pnl                 REAL DEFAULT 0,
            pnl_percent         REAL DEFAULT 0,
            fee_usdt_value      REAL DEFAULT 0,
            stop_loss           REAL,
            trailing_stop_price REAL,
            highest_price       REAL,
            trailing_stop_pct   REAL,
            entry_type          TEXT,
            exit_reason         TEXT,
            signal_strength     REAL,
            atr                 REAL,
            is_open             INTEGER NOT NULL DEFAULT 1,
            holding_period      INTEGER,
            timestamp           INTEGER NOT NULL,
            exit_time           INTEGER,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS config (
            key                 TEXT PRIMARY KEY,
            value               TEXT NOT NULL,
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recovery_queue (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_data          TEXT NOT NULL,
            reason              TEXT NOT NULL,
            resolved            INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_trades_is_open ON trades(is_open);
        CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
    """)


# ─── Trade CRUD ───────────────────────────────────────────────────────────────

def save_trade(trade: dict) -> int:
    """Insert a new trade record. Returns the row id."""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO trades (
            trade_id, symbol, side, direction, quantity, price,
            entry_price, total_value, fee_usdt_value, stop_loss,
            trailing_stop_price, highest_price, trailing_stop_pct,
            entry_type, signal_strength, atr, is_open, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade["trade_id"],
            trade["symbol"],
            trade["side"],
            trade.get("direction", "LONG"),
            trade["quantity"],
            trade["price"],
            trade.get("entry_price", trade["price"]),
            trade.get("total_value", 0),
            trade.get("fee_usdt_value", 0),
            trade.get("stop_loss"),
            trade.get("trailing_stop_price"),
            trade.get("highest_price"),
            trade.get("trailing_stop_pct"),
            trade.get("entry_type"),
            trade.get("signal_strength"),
            trade.get("atr"),
            1 if trade.get("is_open", True) else 0,
            trade.get("timestamp", int(time.time() * 1000)),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def update_trade(trade_id: str, updates: dict) -> None:
    """Update a trade record by trade_id."""
    conn = _get_conn()

    # Build SET clause dynamically
    allowed = {
        "exit_price", "exit_time", "pnl", "pnl_percent", "fee_usdt_value",
        "stop_loss", "trailing_stop_price", "highest_price", "trailing_stop_pct",
        "exit_reason", "is_open", "holding_period", "entry_type",
    }
    sets = []
    values = []
    for key, val in updates.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            values.append(val)

    if not sets:
        return

    sets.append("updated_at = datetime('now')")
    values.append(trade_id)

    sql = f"UPDATE trades SET {', '.join(sets)} WHERE trade_id = ?"
    conn.execute(sql, values)
    conn.commit()


def get_open_trades() -> list[dict]:
    """Get all open trade records."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE is_open = 1 ORDER BY timestamp ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_open_trade_by_symbol(symbol: str) -> Optional[dict]:
    """Get the open trade for a specific symbol, if any."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM trades WHERE symbol = ? AND is_open = 1 LIMIT 1",
        (symbol,),
    ).fetchone()
    return dict(row) if row else None


def get_trade_by_id(trade_id: str) -> Optional[dict]:
    """Get a trade by its trade_id."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM trades WHERE trade_id = ? LIMIT 1",
        (trade_id,),
    ).fetchone()
    return dict(row) if row else None


def get_trades(
    symbol: Optional[str] = None,
    period_ms: Optional[int] = None,
    limit: int = 50,
    open_only: bool = False,
) -> list[dict]:
    """Get trade history with optional filters."""
    conn = _get_conn()
    sql = "SELECT * FROM trades WHERE 1=1"
    params: list = []

    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    if open_only:
        sql += " AND is_open = 1"
    if period_ms:
        cutoff = int(time.time() * 1000) - period_ms
        sql += " AND timestamp >= ?"
        params.append(cutoff)

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_closed_trades(period_ms: Optional[int] = None, symbol: Optional[str] = None) -> list[dict]:
    """Get closed trades for analytics."""
    conn = _get_conn()
    sql = "SELECT * FROM trades WHERE is_open = 0"
    params: list = []

    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    if period_ms:
        cutoff = int(time.time() * 1000) - period_ms
        sql += " AND timestamp >= ?"
        params.append(cutoff)

    sql += " ORDER BY timestamp DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_open_trades() -> int:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM trades WHERE is_open = 1").fetchone()
    return row[0]


def count_all_trades() -> int:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
    return row[0]


# ─── Config CRUD ──────────────────────────────────────────────────────────────

def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a config value by key."""
    conn = _get_conn()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_config_value(key: str, value: str) -> None:
    """Set a config value (upsert)."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value),
    )
    conn.commit()


def get_all_config() -> dict:
    """Get all config key-value pairs."""
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM config ORDER BY key").fetchall()
    return {r[0]: r[1] for r in rows}


def delete_config_value(key: str) -> bool:
    """Delete a config value. Returns True if deleted."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM config WHERE key = ?", (key,))
    conn.commit()
    return cursor.rowcount > 0


# ─── Recovery Queue ───────────────────────────────────────────────────────────

def add_to_recovery_queue(trade_data: dict, reason: str) -> int:
    """Add a failed operation to the recovery queue."""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO recovery_queue (trade_data, reason) VALUES (?, ?)",
        (json.dumps(trade_data, default=str), reason),
    )
    conn.commit()
    return cursor.lastrowid


def get_recovery_queue() -> list[dict]:
    """Get all unresolved recovery queue items."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM recovery_queue WHERE resolved = 0 ORDER BY created_at ASC"
    ).fetchall()
    results = []
    for r in rows:
        item = dict(r)
        try:
            item["trade_data"] = json.loads(item["trade_data"])
        except (json.JSONDecodeError, TypeError):
            pass
        results.append(item)
    return results


def resolve_recovery_item(item_id: int) -> bool:
    """Mark a recovery queue item as resolved."""
    conn = _get_conn()
    cursor = conn.execute(
        "UPDATE recovery_queue SET resolved = 1 WHERE id = ?", (item_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def clear_recovery_item(item_id: int) -> bool:
    """Delete a recovery queue item."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM recovery_queue WHERE id = ?", (item_id,))
    conn.commit()
    return cursor.rowcount > 0


# ─── Period Parsing ───────────────────────────────────────────────────────────

def parse_period(period: str) -> Optional[int]:
    """Parse period string (1d, 7d, 30d, 90d) to milliseconds. Returns None for 'all'."""
    if period == "all":
        return None
    periods = {
        "1d": 1 * 24 * 60 * 60 * 1000,
        "7d": 7 * 24 * 60 * 60 * 1000,
        "30d": 30 * 24 * 60 * 60 * 1000,
        "90d": 90 * 24 * 60 * 60 * 1000,
    }
    return periods.get(period, periods["30d"])
