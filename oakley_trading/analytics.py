"""Analytics — win rate, P&L, profit factor, Sharpe, per-asset breakdown."""

from __future__ import annotations

import math
from typing import Optional

from oakley_trading import db as trade_db


def get_performance(period: str = "30d", symbol: Optional[str] = None) -> dict:
    """Core performance metrics for closed trades.

    Returns {total_trades, winning, losing, win_rate, total_pnl, avg_win,
             avg_loss, profit_factor, total_fees, net_pnl, avg_holding_hours,
             best_trade, worst_trade}.
    """
    period_ms = trade_db.parse_period(period)
    trades = trade_db.get_closed_trades(period_ms=period_ms, symbol=symbol)

    if not trades:
        return {
            "total_trades": 0,
            "winning": 0,
            "losing": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "total_fees": 0.0,
            "net_pnl": 0.0,
            "avg_holding_hours": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "period": period,
        }

    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]

    total_pnl = sum(t.get("pnl") or 0 for t in trades)
    total_fees = sum(t.get("fee_usdt_value") or 0 for t in trades)

    avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(abs(t["pnl"]) for t in losses) / len(losses)) if losses else 0.0
    profit_factor = (avg_win / avg_loss) if avg_loss > 0 else float("inf") if avg_win > 0 else 0.0

    # Holding period
    holding_periods = [t["holding_period"] for t in trades if t.get("holding_period")]
    avg_holding_ms = (sum(holding_periods) / len(holding_periods)) if holding_periods else 0
    avg_holding_hours = avg_holding_ms / (1000 * 60 * 60)

    # Best / worst
    best = max(trades, key=lambda t: t.get("pnl") or 0)
    worst = min(trades, key=lambda t: t.get("pnl") or 0)

    return {
        "total_trades": len(trades),
        "winning": len(wins),
        "losing": len(losses),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_fees": total_fees,
        "net_pnl": total_pnl - total_fees,
        "avg_holding_hours": avg_holding_hours,
        "best_trade": {"symbol": best["symbol"], "pnl": best.get("pnl") or 0, "pnl_percent": best.get("pnl_percent") or 0},
        "worst_trade": {"symbol": worst["symbol"], "pnl": worst.get("pnl") or 0, "pnl_percent": worst.get("pnl_percent") or 0},
        "period": period,
    }


def get_sharpe_ratio(period: str = "30d") -> float:
    """Annualized Sharpe ratio from closed trade returns.

    Uses 0% risk-free rate. Returns 0.0 if fewer than 2 trades.
    """
    period_ms = trade_db.parse_period(period)
    trades = trade_db.get_closed_trades(period_ms=period_ms)

    if len(trades) < 2:
        return 0.0

    # Return per trade as percentage
    returns = [(t.get("pnl_percent") or 0) for t in trades]
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return 0.0

    # Annualize: assume ~365 trades/year as rough scaling
    # Better: scale by actual trading frequency
    sharpe = mean_return / std_dev
    annualized = sharpe * math.sqrt(min(len(trades), 365))
    return annualized


def get_asset_breakdown(period: str = "30d") -> list[dict]:
    """Per-asset performance breakdown.

    Returns list of {symbol, trades, winning, losing, win_rate, total_pnl,
                     avg_pnl, total_fees}.
    """
    period_ms = trade_db.parse_period(period)
    trades = trade_db.get_closed_trades(period_ms=period_ms)

    if not trades:
        return []

    # Group by symbol
    by_symbol: dict[str, list[dict]] = {}
    for t in trades:
        by_symbol.setdefault(t["symbol"], []).append(t)

    results = []
    for symbol, symbol_trades in sorted(by_symbol.items()):
        wins = [t for t in symbol_trades if (t.get("pnl") or 0) > 0]
        losses = [t for t in symbol_trades if (t.get("pnl") or 0) <= 0]
        total_pnl = sum(t.get("pnl") or 0 for t in symbol_trades)
        total_fees = sum(t.get("fee_usdt_value") or 0 for t in symbol_trades)

        results.append({
            "symbol": symbol,
            "trades": len(symbol_trades),
            "winning": len(wins),
            "losing": len(losses),
            "win_rate": (len(wins) / len(symbol_trades) * 100) if symbol_trades else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(symbol_trades),
            "total_fees": total_fees,
        })

    # Sort by total P&L descending
    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    return results


def get_exit_reason_breakdown(period: str = "30d") -> list[dict]:
    """Breakdown by exit reason (STOP_LOSS, TRAILING_STOP, manual_close, etc.).

    Returns list of {reason, trades, total_pnl, avg_pnl, win_rate}.
    """
    period_ms = trade_db.parse_period(period)
    trades = trade_db.get_closed_trades(period_ms=period_ms)

    if not trades:
        return []

    by_reason: dict[str, list[dict]] = {}
    for t in trades:
        reason = t.get("exit_reason") or "unknown"
        by_reason.setdefault(reason, []).append(t)

    results = []
    for reason, reason_trades in sorted(by_reason.items()):
        wins = [t for t in reason_trades if (t.get("pnl") or 0) > 0]
        total_pnl = sum(t.get("pnl") or 0 for t in reason_trades)

        results.append({
            "reason": reason,
            "trades": len(reason_trades),
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(reason_trades),
            "win_rate": (len(wins) / len(reason_trades) * 100) if reason_trades else 0.0,
        })

    return results


def get_full_analytics(period: str = "30d") -> dict:
    """Full analytics dashboard combining all metrics.

    Returns {performance, sharpe_ratio, asset_breakdown, exit_reasons}.
    """
    return {
        "performance": get_performance(period),
        "sharpe_ratio": get_sharpe_ratio(period),
        "asset_breakdown": get_asset_breakdown(period),
        "exit_reasons": get_exit_reason_breakdown(period),
    }
