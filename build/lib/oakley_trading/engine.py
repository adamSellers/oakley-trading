"""Trading engine — buy/sell/close flows, portfolio state, position tracking."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from oakley_trading.common.config import Config
from oakley_trading import data_service
from oakley_trading import db as trade_db


# ─── Helper Functions ────────────────────────────────────────────────────────


def _get_effective_config(key: str) -> float:
    """Get config value with DB override taking precedence over Config default."""
    db_val = trade_db.get_config_value(key)
    if db_val is not None:
        return float(db_val)
    return float(getattr(Config, key))


def _get_usdt_balance() -> float:
    """Get available USDT balance from Binance account."""
    account = data_service.get_account()
    if account.get("error"):
        raise RuntimeError(f"Cannot fetch account: {account['error']}")
    usdt = next((b for b in account["balances"] if b["asset"] == "USDT"), None)
    if usdt is None:
        return 0.0
    return usdt["free"]


def _calculate_equity() -> tuple[float, float, list[dict]]:
    """Calculate total equity including open positions.

    Returns (total_equity, usdt_balance, enriched_positions).
    """
    usdt_balance = _get_usdt_balance()
    open_trades = trade_db.get_open_trades()
    enriched = []
    crypto_value = 0.0

    for trade in open_trades:
        try:
            price_data = data_service.get_price(trade["symbol"])
            current_price = price_data["price"] if price_data else trade["price"]
        except Exception:
            current_price = trade["price"]

        current_value = current_price * trade["quantity"]
        entry_cost = trade["entry_price"] * trade["quantity"]
        unrealized_pnl = current_value - entry_cost
        unrealized_pnl_pct = (unrealized_pnl / entry_cost * 100) if entry_cost > 0 else 0

        enriched.append({
            **trade,
            "current_price": current_price,
            "current_value": current_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
        })
        crypto_value += current_value

    total_equity = usdt_balance + crypto_value
    return total_equity, usdt_balance, enriched


def calculate_order_fee(order: dict) -> float:
    """Calculate total fee in USDT from Binance order fills.

    Converts BNB and other asset fees to USDT via current price.
    """
    total_fee_usdt = 0.0

    for fill in order.get("fills", []):
        try:
            fee = float(fill.get("commission", 0))
            fee_asset = fill.get("commissionAsset", "USDT")

            if fee_asset == "USDT":
                total_fee_usdt += fee
            elif fee_asset == "BNB":
                bnb_price = data_service.get_price("BNBUSDT")
                if bnb_price:
                    total_fee_usdt += fee * bnb_price["price"]
            else:
                asset_price = data_service.get_price(f"{fee_asset}USDT")
                if asset_price:
                    total_fee_usdt += fee * asset_price["price"]
        except Exception:
            continue

    return total_fee_usdt


def _acquire_lock(symbol: str) -> bool:
    """Acquire file-based lock for a symbol. Returns True if acquired."""
    Config.ensure_dirs()
    lock_path = Config.lock_dir / f".lock_{symbol}"

    # Check for stale lock (> 5 minutes)
    if lock_path.exists():
        try:
            content = lock_path.read_text().strip()
            parts = content.split("|")
            if len(parts) == 2:
                lock_time = float(parts[1])
                if time.time() - lock_time > 300:
                    lock_path.unlink(missing_ok=True)
                else:
                    return False
        except (ValueError, OSError):
            lock_path.unlink(missing_ok=True)

    try:
        lock_path.write_text(f"{os.getpid()}|{time.time()}")
        return True
    except OSError:
        return False


def _release_lock(symbol: str) -> None:
    """Release file-based lock for a symbol."""
    lock_path = Config.lock_dir / f".lock_{symbol}"
    lock_path.unlink(missing_ok=True)


# ─── Core Functions ──────────────────────────────────────────────────────────


def buy(
    symbol: str,
    allocation: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    entry_type: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Execute a buy order (or simulate with dry_run).

    Returns {"success": True, "trade": {...}, "dry_run": bool}
    or {"success": False, "reason": "..."}.
    """
    # Check halt
    if trade_db.get_config_value("trading_halted") == "1":
        return {"success": False, "reason": "Trading is halted"}

    # Check existing position
    existing = trade_db.get_open_trade_by_symbol(symbol)
    if existing:
        return {"success": False, "reason": f"Already have an open position in {symbol}"}

    # Resolve config
    alloc = allocation or _get_effective_config("default_allocation")
    sl_pct = stop_loss_pct if stop_loss_pct is not None else _get_effective_config("default_stop_loss_pct")
    ts_pct = trailing_stop_pct if trailing_stop_pct is not None else _get_effective_config("default_trailing_stop_pct")
    risk = _get_effective_config("risk_per_trade")
    min_trade = _get_effective_config("min_trade_usdt")
    cash_buffer = _get_effective_config("cash_buffer")
    max_exposure = _get_effective_config("max_portfolio_exposure")
    max_cap = _get_effective_config("max_capital_at_risk")

    # Get equity and exposure
    try:
        total_equity, usdt_balance, positions = _calculate_equity()
    except RuntimeError as e:
        return {"success": False, "reason": str(e)}

    if total_equity <= 0:
        return {"success": False, "reason": "No equity available"}

    # Current exposure
    crypto_value = sum(p["current_value"] for p in positions)
    current_exposure = crypto_value / total_equity if total_equity > 0 else 0
    remaining_exposure = max(0, max_exposure - current_exposure)

    if remaining_exposure <= 0:
        return {"success": False, "reason": f"Portfolio exposure at {current_exposure:.0%}, max is {max_exposure:.0%}"}

    # Position sizing
    target = min(alloc * total_equity, remaining_exposure * total_equity)
    trade_amount = target * risk
    trade_amount = min(trade_amount, max_cap)

    if trade_amount > usdt_balance:
        trade_amount = usdt_balance * (1 - cash_buffer)

    if trade_amount < min_trade:
        return {"success": False, "reason": f"Trade amount ${trade_amount:.2f} below minimum ${min_trade:.2f}"}

    # Get current price
    price_data = data_service.get_price(symbol)
    if price_data is None:
        return {"success": False, "reason": f"Cannot fetch price for {symbol}"}
    current_price = price_data["price"]

    quantity = trade_amount / current_price

    # Calculate stop levels
    stop_loss_type = (trade_db.get_config_value("stop_loss_type") or Config.stop_loss_type).upper()
    atr_value = None

    if stop_loss_type == "ATR":
        atr_multiplier = _get_effective_config("stop_loss_atr_multiplier")
        atr_value = data_service.calculate_atr(symbol)
        if atr_value is not None:
            stop_loss_price = current_price - (atr_value * atr_multiplier)
        else:
            stop_loss_price = current_price * (1 - sl_pct)
    else:
        stop_loss_price = current_price * (1 - sl_pct)

    trailing_stop_price = current_price * (1 - ts_pct) if ts_pct > 0 else None

    if dry_run:
        estimated_fee = trade_amount * 0.001
        trade_info = {
            "symbol": symbol,
            "side": "BUY",
            "quantity": data_service.step_size(symbol, quantity),
            "price": current_price,
            "entry_price": current_price,
            "total_value": trade_amount,
            "fee_usdt_value": estimated_fee,
            "stop_loss": stop_loss_price,
            "trailing_stop_price": trailing_stop_price,
            "trailing_stop_pct": ts_pct,
            "highest_price": current_price,
            "entry_type": entry_type,
            "allocation_used": alloc,
            "atr": atr_value,
            "stop_loss_type": stop_loss_type,
        }
        return {"success": True, "trade": trade_info, "dry_run": True}

    # Live order
    try:
        order = data_service.execute_order(symbol, "BUY", quantity)
    except Exception as e:
        return {"success": False, "reason": f"Order failed: {e}"}

    # Parse response
    executed_qty = float(order.get("executedQty", 0))
    cumulative_quote = float(order.get("cummulativeQuoteQty", 0))
    if executed_qty <= 0:
        return {"success": False, "reason": "Order filled 0 quantity"}

    entry_price = cumulative_quote / executed_qty
    total_value = cumulative_quote
    entry_fee = calculate_order_fee(order)

    # Recalculate stops with actual entry price
    if stop_loss_type == "ATR" and atr_value is not None:
        stop_loss_price = entry_price - (atr_value * atr_multiplier)
    else:
        stop_loss_price = entry_price * (1 - sl_pct)
    trailing_stop_price = entry_price * (1 - ts_pct) if ts_pct > 0 else None

    trade_record = {
        "trade_id": str(order.get("orderId", f"UNKNOWN_{int(time.time() * 1000)}")),
        "symbol": symbol,
        "side": "BUY",
        "direction": "LONG",
        "quantity": executed_qty,
        "price": entry_price,
        "entry_price": entry_price,
        "total_value": total_value,
        "fee_usdt_value": entry_fee,
        "stop_loss": stop_loss_price,
        "trailing_stop_price": trailing_stop_price,
        "highest_price": entry_price,
        "trailing_stop_pct": ts_pct,
        "entry_type": entry_type,
        "atr": atr_value,
        "is_open": True,
        "timestamp": int(time.time() * 1000),
    }

    try:
        trade_db.save_trade(trade_record)
    except Exception:
        trade_db.add_to_recovery_queue(trade_record, "save_trade_failed_after_buy")

    return {"success": True, "trade": trade_record, "dry_run": False}


def sell(symbol: str, reason: Optional[str] = None, dry_run: bool = False) -> dict:
    """Sell/close an open position by symbol.

    Returns result from close_position() or failure dict.
    """
    trade = trade_db.get_open_trade_by_symbol(symbol)
    if not trade:
        return {"success": False, "reason": f"No open position found for {symbol}"}
    return close_position(trade, reason=reason, dry_run=dry_run)


def close_position(trade: dict, reason: Optional[str] = None, dry_run: bool = False) -> dict:
    """Close an open trade position.

    Returns {"success": True, "trade_id": ..., "pnl": ..., ...}
    or {"success": False, "reason": "..."}.
    """
    symbol = trade["symbol"]
    quantity = trade["quantity"]
    entry_price = trade.get("entry_price", trade["price"])

    # Get current price
    price_data = data_service.get_price(symbol)
    if price_data is None:
        return {"success": False, "reason": f"Cannot fetch price for {symbol}"}
    current_price = price_data["price"]

    # P&L calculation
    gross_pnl = (current_price * quantity) - (entry_price * quantity)
    pnl_pct = (gross_pnl / (entry_price * quantity) * 100) if entry_price * quantity > 0 else 0

    if dry_run:
        estimated_fee = (current_price * quantity) * 0.001
        total_fees = trade.get("fee_usdt_value", 0) + estimated_fee
        return {
            "success": True,
            "trade_id": trade["trade_id"],
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": current_price,
            "quantity": quantity,
            "pnl": gross_pnl,
            "pnl_percent": pnl_pct,
            "fee_usdt_value": total_fees,
            "reason": reason or "manual_close",
            "dry_run": True,
        }

    # Live close — acquire lock
    if not _acquire_lock(symbol):
        return {"success": False, "reason": f"Cannot acquire lock for {symbol} — another close may be in progress"}

    try:
        # Execute sell order
        try:
            order = data_service.execute_order(symbol, "SELL", quantity)
        except Exception as e:
            return {"success": False, "reason": f"Sell order failed: {e}"}

        executed_qty = float(order.get("executedQty", 0))
        cumulative_quote = float(order.get("cummulativeQuoteQty", 0))
        if executed_qty <= 0:
            return {"success": False, "reason": "Sell order filled 0 quantity"}

        exit_price = cumulative_quote / executed_qty
        exit_fee = calculate_order_fee(order)
        total_fees = trade.get("fee_usdt_value", 0) + exit_fee

        # Final P&L with actual exit price
        gross_pnl = (exit_price * executed_qty) - (entry_price * quantity)
        pnl_pct = (gross_pnl / (entry_price * quantity) * 100) if entry_price * quantity > 0 else 0

        exit_time = int(time.time() * 1000)
        holding_period = exit_time - trade["timestamp"]

        updates = {
            "is_open": 0,
            "exit_price": exit_price,
            "exit_time": exit_time,
            "pnl": gross_pnl,
            "pnl_percent": pnl_pct,
            "fee_usdt_value": total_fees,
            "exit_reason": reason or "manual_close",
            "holding_period": holding_period,
        }

        try:
            trade_db.update_trade(trade["trade_id"], updates)
        except Exception:
            trade_db.add_to_recovery_queue(
                {"trade_id": trade["trade_id"], "updates": updates},
                "update_trade_failed_after_sell",
            )

        return {
            "success": True,
            "trade_id": trade["trade_id"],
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": executed_qty,
            "pnl": gross_pnl,
            "pnl_percent": pnl_pct,
            "fee_usdt_value": total_fees,
            "holding_period": holding_period,
            "reason": reason or "manual_close",
            "dry_run": False,
        }
    finally:
        _release_lock(symbol)


def get_portfolio() -> dict:
    """Get portfolio overview with all open positions.

    Returns {usdt_balance, total_equity, crypto_value, positions,
             exposure_pct, open_count, total_unrealized_pnl}.
    """
    try:
        total_equity, usdt_balance, positions = _calculate_equity()
    except RuntimeError as e:
        return {"error": str(e)}

    crypto_value = sum(p["current_value"] for p in positions)
    exposure_pct = (crypto_value / total_equity * 100) if total_equity > 0 else 0
    total_unrealized = sum(p["unrealized_pnl"] for p in positions)

    return {
        "usdt_balance": usdt_balance,
        "total_equity": total_equity,
        "crypto_value": crypto_value,
        "positions": positions,
        "exposure_pct": exposure_pct,
        "open_count": len(positions),
        "total_unrealized_pnl": total_unrealized,
    }


def get_positions(symbol: Optional[str] = None) -> dict:
    """Get enriched open positions, optionally filtered by symbol.

    Returns {"positions": [...]} or {"error": "..."}.
    """
    try:
        _, _, positions = _calculate_equity()
    except RuntimeError as e:
        return {"error": str(e)}

    if symbol:
        positions = [p for p in positions if p["symbol"] == symbol]
    return {"positions": positions}
