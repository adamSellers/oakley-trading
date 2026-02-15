"""Reconciliation — exchange state vs DB state, recovery queue retry."""

from __future__ import annotations

from oakley_trading import data_service
from oakley_trading import db as trade_db


def _extract_asset_from_symbol(symbol: str) -> str:
    """Extract base asset from USDT trading pair. E.g. BTCUSDT -> BTC."""
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol


def detect_zombies(
    open_trades: list[dict], balances: dict[str, float]
) -> list[dict]:
    """Detect DB positions with no corresponding exchange balance.

    A zombie is a trade the DB considers open, but the exchange has no
    (or negligible) balance for that asset.
    """
    zombies = []
    for trade in open_trades:
        try:
            asset = _extract_asset_from_symbol(trade["symbol"])
            exchange_bal = balances.get(asset, 0.0)
            db_qty = trade["quantity"]

            # Zombie if exchange balance is 0 or < 1% of DB quantity
            if exchange_bal < db_qty * 0.01:
                zombies.append({
                    "trade_id": trade["trade_id"],
                    "symbol": trade["symbol"],
                    "db_quantity": db_qty,
                    "exchange_balance": exchange_bal,
                    "type": "zombie",
                })
        except Exception:
            zombies.append({
                "trade_id": trade.get("trade_id", "unknown"),
                "symbol": trade.get("symbol", "unknown"),
                "db_quantity": trade.get("quantity", 0),
                "exchange_balance": 0.0,
                "type": "zombie",
                "error": True,
            })
    return zombies


def detect_orphans(
    open_trades: list[dict],
    balances: dict[str, float],
    prices: dict[str, float],
) -> list[dict]:
    """Detect exchange balances not tracked in the DB.

    An orphan is a non-trivial crypto balance on the exchange that has
    no corresponding open trade in the DB. Skips USDT and BNB.
    """
    tracked_assets = {
        _extract_asset_from_symbol(t["symbol"]) for t in open_trades
    }
    skip_assets = {"USDT", "BNB"}

    orphans = []
    for asset, balance in balances.items():
        if asset in skip_assets or balance <= 0:
            continue
        if asset in tracked_assets:
            continue

        symbol = asset + "USDT"
        price = prices.get(symbol, 0.0)
        value_usdt = balance * price

        # Filter out dust (< $1)
        if value_usdt < 1.0 and price > 0:
            continue

        orphans.append({
            "asset": asset,
            "symbol": symbol,
            "exchange_balance": balance,
            "estimated_value_usdt": value_usdt,
            "type": "orphan",
        })

    return orphans


def detect_mismatches(
    open_trades: list[dict], balances: dict[str, float]
) -> list[dict]:
    """Detect quantity differences between DB and exchange.

    A mismatch is when both DB and exchange have non-zero quantities
    for the same asset, but they differ by more than 1%.
    """
    mismatches = []
    for trade in open_trades:
        try:
            asset = _extract_asset_from_symbol(trade["symbol"])
            exchange_bal = balances.get(asset, 0.0)
            db_qty = trade["quantity"]

            if exchange_bal <= 0 or db_qty <= 0:
                continue  # Handled by zombie detection

            diff = exchange_bal - db_qty
            diff_pct = abs(diff) / db_qty * 100

            if diff_pct > 1.0:
                mismatches.append({
                    "trade_id": trade["trade_id"],
                    "symbol": trade["symbol"],
                    "db_quantity": db_qty,
                    "exchange_balance": exchange_bal,
                    "difference": diff,
                    "difference_pct": diff_pct,
                    "type": "mismatch",
                })
        except Exception:
            pass  # Skip on error, don't crash reconciliation
    return mismatches


def reconcile() -> dict:
    """Run full reconciliation: compare DB state vs Binance exchange state.

    Returns a diagnostic report. Does NOT auto-fix anything.
    """
    # Fetch exchange state
    account = data_service.get_account()
    if account.get("error"):
        return {
            "success": False,
            "error": f"Cannot fetch account: {account['error']}",
            "zombies": [],
            "orphans": [],
            "mismatches": [],
            "total_issues": 0,
            "open_trades_checked": 0,
            "exchange_assets_checked": 0,
        }

    # Build balances dict: {asset: total_balance}
    balances = {}
    for b in account["balances"]:
        balances[b["asset"]] = b["total"]

    # Fetch DB state
    open_trades = trade_db.get_open_trades()

    # Fetch prices for orphan value estimation
    # Collect all non-USDT/BNB assets with balances
    prices = {}
    price_assets = {
        a for a, bal in balances.items()
        if a not in ("USDT", "BNB") and bal > 0
    }
    for asset in price_assets:
        try:
            symbol = asset + "USDT"
            result = data_service.get_price(symbol)
            if result:
                prices[symbol] = result["price"]
        except Exception:
            pass  # Price unknown — orphan will show $0 value

    # Run detection
    zombies = detect_zombies(open_trades, balances)
    orphans = detect_orphans(open_trades, balances, prices)
    mismatches = detect_mismatches(open_trades, balances)

    return {
        "success": True,
        "zombies": zombies,
        "orphans": orphans,
        "mismatches": mismatches,
        "total_issues": len(zombies) + len(orphans) + len(mismatches),
        "open_trades_checked": len(open_trades),
        "exchange_assets_checked": len(price_assets),
        "error": None,
    }


def retry_recovery_item(item: dict) -> dict:
    """Attempt to replay a failed DB operation from the recovery queue.

    Only retries DB writes — the exchange order already succeeded.
    """
    reason = item.get("reason", "")
    trade_data = item.get("trade_data", {})

    try:
        if reason == "save_trade_failed_after_buy":
            trade_db.save_trade(trade_data)
            trade_db.resolve_recovery_item(item["id"])
            return {
                "success": True,
                "action": "saved_trade",
                "trade_id": trade_data.get("trade_id", "unknown"),
            }

        if reason == "update_trade_failed_after_sell":
            tid = trade_data.get("trade_id", "")
            updates = trade_data.get("updates", {})
            if not tid or not updates:
                return {"success": False, "reason": "Missing trade_id or updates in recovery data"}
            trade_db.update_trade(tid, updates)
            trade_db.resolve_recovery_item(item["id"])
            return {
                "success": True,
                "action": "updated_trade",
                "trade_id": tid,
            }

        return {"success": False, "reason": f"Unknown recovery type: {reason}"}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def retry_all_recovery() -> dict:
    """Retry all unresolved recovery queue items."""
    items = trade_db.get_recovery_queue()
    results = {
        "total": len(items),
        "succeeded": 0,
        "failed": 0,
        "details": [],
    }

    for item in items:
        result = retry_recovery_item(item)
        if result["success"]:
            results["succeeded"] += 1
        else:
            results["failed"] += 1
        results["details"].append({
            "id": item["id"],
            "reason": item["reason"],
            "result": result,
        })

    return results
