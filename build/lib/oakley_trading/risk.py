"""Risk management — stop-loss enforcement, trailing stops, halt control, risk dashboard."""

from __future__ import annotations

from typing import Optional

from oakley_trading.common.config import Config
from oakley_trading import data_service
from oakley_trading import db as trade_db


def _get_effective_config(key: str) -> float:
    """Get config value with DB override taking precedence over Config default."""
    db_val = trade_db.get_config_value(key)
    if db_val is not None:
        return float(db_val)
    return float(getattr(Config, key))


def check_exit_conditions(symbol: Optional[str] = None) -> dict:
    """Check all open positions for stop-loss / trailing stop breach.

    For each position:
    1. Fetch current price
    2. Check fixed stop-loss breach
    3. If trailing stops enabled: ratchet highest_price, compute trailing stop, check breach
    4. If breached: close via engine.close_position()

    Returns {"checked": N, "closed": N, "errors": N, "details": [...]}.
    """
    open_trades = trade_db.get_open_trades()
    if symbol:
        open_trades = [t for t in open_trades if t["symbol"] == symbol]

    enable_trailing = trade_db.get_config_value("enable_trailing_stops")
    if enable_trailing is None:
        enable_trailing = Config.enable_trailing_stops
    else:
        enable_trailing = str(enable_trailing).lower() in ("1", "true", "yes")

    results = {
        "checked": 0,
        "closed": 0,
        "errors": 0,
        "details": [],
    }

    for trade in open_trades:
        try:
            detail = _check_single_position(trade, enable_trailing)
            results["checked"] += 1
            results["details"].append(detail)
            if detail.get("closed"):
                results["closed"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "symbol": trade["symbol"],
                "error": str(e),
            })

    return results


def _check_single_position(trade: dict, enable_trailing: bool) -> dict:
    """Check a single position for exit conditions."""
    symbol = trade["symbol"]
    entry_price = trade.get("entry_price", trade["price"])

    price_data = data_service.get_price(symbol)
    if price_data is None:
        raise RuntimeError(f"Cannot fetch price for {symbol}")
    current_price = price_data["price"]

    detail = {
        "symbol": symbol,
        "current_price": current_price,
        "entry_price": entry_price,
        "closed": False,
        "reason": None,
    }

    # 1. Check fixed stop-loss
    stop_loss = trade.get("stop_loss")
    if stop_loss and current_price <= stop_loss:
        detail["reason"] = "STOP_LOSS"
        detail["trigger_price"] = stop_loss
        _close_triggered(trade, "STOP_LOSS")
        detail["closed"] = True
        return detail

    # 2. Trailing stop (if enabled and position has trailing stop data)
    if enable_trailing and trade.get("trailing_stop_pct") and trade["trailing_stop_pct"] > 0:
        highest = trade.get("highest_price") or entry_price
        trailing_pct = trade["trailing_stop_pct"]

        # Ratchet up if new high
        if current_price > highest:
            highest = current_price
            new_trailing = highest * (1 - trailing_pct)

            # Update DB immediately (persists even if process crashes after)
            trade_db.update_trade(trade["trade_id"], {
                "highest_price": highest,
                "trailing_stop_price": new_trailing,
            })

            detail["highest_price_updated"] = highest
            detail["trailing_stop_updated"] = new_trailing

        # Current trailing stop (use updated value if just ratcheted)
        if detail.get("trailing_stop_updated"):
            trailing_stop = detail["trailing_stop_updated"]
        else:
            trailing_stop = trade.get("trailing_stop_price")

        if trailing_stop and current_price <= trailing_stop:
            detail["reason"] = "TRAILING_STOP"
            detail["trigger_price"] = trailing_stop
            _close_triggered(trade, "TRAILING_STOP")
            detail["closed"] = True
            return detail

    return detail


def _close_triggered(trade: dict, reason: str) -> dict:
    """Close a position due to risk trigger. Uses lazy import to avoid circular dep."""
    from oakley_trading import engine
    return engine.close_position(trade, reason=reason)


def halt() -> dict:
    """Halt all trading. Buys are refused; sells and check-exits still work."""
    trade_db.set_config_value("trading_halted", "1")
    return {"halted": True, "message": "Trading halted. Sells and stop-loss enforcement remain active."}


def resume() -> dict:
    """Resume trading after a halt."""
    trade_db.set_config_value("trading_halted", "0")
    return {"halted": False, "message": "Trading resumed."}


def get_risk_status() -> dict:
    """Get current risk dashboard: exposure, positions, halt state, config thresholds."""
    open_trades = trade_db.get_open_trades()

    total_crypto_value = 0.0
    position_details = []

    for trade in open_trades:
        try:
            price_data = data_service.get_price(trade["symbol"])
            current_price = price_data["price"] if price_data else trade["price"]
        except Exception:
            current_price = trade["price"]

        value = current_price * trade["quantity"]
        total_crypto_value += value

        distance_to_stop = None
        if trade.get("stop_loss") and current_price > 0:
            distance_to_stop = (current_price - trade["stop_loss"]) / current_price * 100

        position_details.append({
            "symbol": trade["symbol"],
            "current_price": current_price,
            "value": value,
            "stop_loss": trade.get("stop_loss"),
            "trailing_stop_price": trade.get("trailing_stop_price"),
            "highest_price": trade.get("highest_price"),
            "distance_to_stop_pct": distance_to_stop,
        })

    # Get USDT balance for exposure calc
    try:
        account = data_service.get_account()
        usdt_balance = 0.0
        if not account.get("error"):
            usdt = next((b for b in account["balances"] if b["asset"] == "USDT"), None)
            if usdt:
                usdt_balance = usdt["free"]
    except Exception:
        usdt_balance = 0.0

    total_equity = usdt_balance + total_crypto_value
    exposure_pct = (total_crypto_value / total_equity * 100) if total_equity > 0 else 0

    halted = trade_db.get_config_value("trading_halted") == "1"

    return {
        "halted": halted,
        "open_positions": len(open_trades),
        "total_equity": total_equity,
        "crypto_value": total_crypto_value,
        "usdt_balance": usdt_balance,
        "exposure_pct": exposure_pct,
        "max_exposure_pct": _get_effective_config("max_portfolio_exposure") * 100,
        "stop_loss_type": (trade_db.get_config_value("stop_loss_type") or Config.stop_loss_type),
        "default_stop_loss_pct": _get_effective_config("default_stop_loss_pct") * 100,
        "default_trailing_stop_pct": _get_effective_config("default_trailing_stop_pct") * 100,
        "enable_trailing_stops": str(
            trade_db.get_config_value("enable_trailing_stops") or Config.enable_trailing_stops
        ),
        "positions": position_details,
    }
