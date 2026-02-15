"""Unified CLI dispatcher for all oakley-trading commands."""

import argparse
import sys


def cmd_setup(args):
    from oakley_trading import auth

    if not args.api_key or not args.api_secret:
        print("Error: --api-key and --api-secret are required.", file=sys.stderr)
        sys.exit(1)

    auth.save_credentials(args.api_key, args.api_secret)
    print("Binance credentials saved.")

    # Test connection
    from oakley_trading.client import test_connection
    result = test_connection()
    if result["connected"]:
        print(f"Connection test: OK ({result['status']})")
    else:
        print(f"Connection test: FAILED — {result['error']}")
        print("Credentials saved but connection failed. Check your API key/secret.")


def cmd_status(args):
    from oakley_trading import __version__
    from oakley_trading import auth
    from oakley_trading.common import Config, format_datetime_aedt

    Config.ensure_dirs()

    lines = [
        f"Oakley Trading v{__version__}",
        f"Time: {format_datetime_aedt()}",
        "",
    ]

    # Credentials check
    if not auth.has_credentials():
        lines.append("Status: NOT CONFIGURED")
        lines.append("Run: oakley-trading setup --api-key KEY --api-secret SECRET")
        print("\n".join(lines))
        return

    # Connection check
    from oakley_trading.client import test_connection
    conn = test_connection()
    if conn["connected"]:
        lines.append(f"Binance: connected ({conn['status']})")
    else:
        lines.append(f"Binance: DISCONNECTED — {conn['error']}")
        print("\n".join(lines))
        return

    # Account summary
    from oakley_trading import data_service
    account = data_service.get_account()
    if not account.get("error"):
        usdt = next((b for b in account["balances"] if b["asset"] == "USDT"), None)
        if usdt:
            lines.append(f"USDT Balance: ${usdt['free']:,.2f} (locked: ${usdt['locked']:,.2f})")

    # DB status
    try:
        from oakley_trading import db as trade_db
        open_count = trade_db.count_open_trades()
        total_count = trade_db.count_all_trades()
        lines.append(f"Open positions: {open_count}")
        lines.append(f"Total trades: {total_count}")

        # Halt status
        halted = trade_db.get_config_value("trading_halted")
        if halted == "1":
            lines.append("TRADING HALTED")
    except Exception:
        lines.append("Database: not initialized")

    lines.append("")
    lines.append(f"Data directory: {Config.data_dir}")

    print("\n".join(lines))


def cmd_account(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header
    from oakley_trading import data_service

    account = data_service.get_account()
    if account.get("error"):
        print(f"Error: {account['error']}", file=sys.stderr)
        sys.exit(1)

    balances = account["balances"]
    if not balances:
        print("No balances found.")
        return

    lines = [format_section_header("Account Balances"), ""]

    # USDT first
    usdt = next((b for b in balances if b["asset"] == "USDT"), None)
    if usdt:
        lines.append(f"USDT: ${usdt['free']:,.2f} free, ${usdt['locked']:,.2f} locked")

    # BNB next
    bnb = next((b for b in balances if b["asset"] == "BNB"), None)
    if bnb:
        lines.append(f"BNB: {bnb['free']:.4f} free, {bnb['locked']:.4f} locked")

    # Other non-zero balances
    others = [b for b in balances if b["asset"] not in ("USDT", "BNB")]
    if others:
        lines.append("")
        for b in sorted(others, key=lambda x: x["total"], reverse=True):
            if b["total"] > 0:
                lines.append(f"{b['asset']}: {b['free']:.6f} free, {b['locked']:.6f} locked")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_price(args):
    from oakley_trading import data_service

    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    result = data_service.get_price(symbol)
    if result is None:
        print(f"Error: Could not fetch price for {symbol}", file=sys.stderr)
        sys.exit(1)

    stale = " (cached)" if result.get("_stale") else ""
    print(f"{result['symbol']}: ${result['price']:,.8g}{stale}")


def cmd_prices(args):
    from oakley_trading.common import truncate_for_telegram
    from oakley_trading import data_service

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        symbols = [s if s.endswith("USDT") else s + "USDT" for s in symbols]

    results = data_service.get_prices(symbols)
    if not results:
        print("No prices available.")
        return

    lines = []
    for r in sorted(results, key=lambda x: x["symbol"]):
        lines.append(f"{r['symbol']}: ${r['price']:,.8g}")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_candles(args):
    from oakley_trading.common import truncate_for_telegram
    from oakley_trading import data_service
    from datetime import datetime

    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    valid_intervals = [
        "1m", "3m", "5m", "15m", "30m",
        "1h", "2h", "4h", "6h", "8h", "12h",
        "1d", "3d", "1w", "1M",
    ]
    interval = args.timeframe
    if interval not in valid_intervals:
        print(f"Error: Invalid timeframe '{interval}'. Valid: {', '.join(valid_intervals)}", file=sys.stderr)
        sys.exit(1)

    limit = args.limit or 20
    candles = data_service.get_candles(symbol, interval, limit)
    if not candles:
        print(f"No candle data for {symbol} {interval}")
        return

    lines = [f"{symbol} {interval} (last {len(candles)} candles)", ""]
    lines.append("Time                | Open       | High       | Low        | Close      | Volume")
    lines.append("-" * 90)

    for c in candles[-limit:]:
        dt = datetime.fromtimestamp(c["open_time"] / 1000).strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"{dt} | {c['open']:>10.4f} | {c['high']:>10.4f} | "
            f"{c['low']:>10.4f} | {c['close']:>10.4f} | {c['volume']:>10.1f}"
        )

    print(truncate_for_telegram("\n".join(lines)))


def cmd_trades(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header, format_currency
    from oakley_trading import db as trade_db
    from datetime import datetime

    period_ms = trade_db.parse_period(args.period) if args.period else None
    symbol = args.symbol.upper() if args.symbol else None
    if symbol and not symbol.endswith("USDT"):
        symbol += "USDT"

    trades = trade_db.get_trades(symbol=symbol, period_ms=period_ms, limit=args.limit)
    if not trades:
        print("No trades found.")
        return

    lines = [format_section_header(f"Trade History ({len(trades)} trades)"), ""]

    for t in trades:
        dt = datetime.fromtimestamp(t["timestamp"] / 1000).strftime("%Y-%m-%d %H:%M")
        status = "OPEN" if t["is_open"] else "CLOSED"
        pnl_str = ""
        if not t["is_open"] and t["pnl"]:
            pnl_str = f" | P&L: {format_currency(t['pnl'])}"
        reason = f" ({t['exit_reason']})" if t.get("exit_reason") and not t["is_open"] else ""
        entry = f" [{t['entry_type']}]" if t.get("entry_type") else ""
        lines.append(
            f"{dt} | {t['side']} {t['symbol']} | "
            f"qty: {t['quantity']:.6f} @ ${t['price']:,.2f} | "
            f"{status}{reason}{pnl_str}{entry}"
        )

    print(truncate_for_telegram("\n".join(lines)))


def cmd_buy(args):
    from oakley_trading.common import truncate_for_telegram, format_currency, format_number
    from oakley_trading import engine

    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    result = engine.buy(
        symbol=symbol,
        allocation=args.allocation,
        stop_loss_pct=args.stop_loss,
        trailing_stop_pct=args.trailing_stop,
        entry_type=args.reason,
        dry_run=args.dry_run,
    )

    if not result["success"]:
        print(f"Buy refused: {result['reason']}", file=sys.stderr)
        sys.exit(1)

    t = result["trade"]
    prefix = "[DRY RUN] " if result["dry_run"] else ""

    lines = [
        f"{prefix}BUY {t['symbol']}",
        f"Quantity: {format_number(t['quantity'], 6)}",
        f"Entry price: ${t['entry_price']:,.2f}",
        f"Total value: ${t['total_value']:,.2f}",
        f"Fee: ${t['fee_usdt_value']:,.4f}",
        f"Stop-loss: ${t['stop_loss']:,.2f}",
    ]
    if t.get("trailing_stop_price"):
        lines.append(f"Trailing stop: ${t['trailing_stop_price']:,.2f} ({t['trailing_stop_pct']:.1%})")
    if t.get("entry_type"):
        lines.append(f"Reason: {t['entry_type']}")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_sell(args):
    from oakley_trading.common import truncate_for_telegram, format_currency
    from oakley_trading import engine

    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    result = engine.sell(symbol=symbol, reason=args.reason, dry_run=args.dry_run)

    if not result["success"]:
        print(f"Sell failed: {result['reason']}", file=sys.stderr)
        sys.exit(1)

    _print_close_result(result)


def cmd_close(args):
    from oakley_trading import db as trade_db
    from oakley_trading import engine

    trade = trade_db.get_trade_by_id(args.trade_id)
    if not trade:
        print(f"Error: Trade '{args.trade_id}' not found.", file=sys.stderr)
        sys.exit(1)
    if not trade["is_open"]:
        print(f"Error: Trade '{args.trade_id}' is already closed.", file=sys.stderr)
        sys.exit(1)

    result = engine.close_position(trade, reason=args.reason, dry_run=args.dry_run)

    if not result["success"]:
        print(f"Close failed: {result['reason']}", file=sys.stderr)
        sys.exit(1)

    _print_close_result(result)


def _print_close_result(result: dict):
    """Format and print a close/sell result."""
    from oakley_trading.common import truncate_for_telegram, format_currency

    prefix = "[DRY RUN] " if result.get("dry_run") else ""
    pnl_sign = "+" if result["pnl"] >= 0 else ""

    lines = [
        f"{prefix}CLOSED {result['symbol']}",
        f"Entry: ${result['entry_price']:,.2f} → Exit: ${result['exit_price']:,.2f}",
        f"Quantity: {result['quantity']:.6f}",
        f"P&L: {pnl_sign}{format_currency(result['pnl'])} ({pnl_sign}{result['pnl_percent']:.2f}%)",
        f"Fees: ${result['fee_usdt_value']:,.4f}",
    ]
    if result.get("holding_period"):
        hours = result["holding_period"] / (1000 * 60 * 60)
        if hours >= 24:
            lines.append(f"Held: {hours / 24:.1f} days")
        else:
            lines.append(f"Held: {hours:.1f} hours")
    if result.get("reason"):
        lines.append(f"Reason: {result['reason']}")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_portfolio(args):
    from oakley_trading.common import truncate_for_telegram, format_currency, format_section_header
    from oakley_trading import engine

    portfolio = engine.get_portfolio()
    if portfolio.get("error"):
        print(f"Error: {portfolio['error']}", file=sys.stderr)
        sys.exit(1)

    lines = [
        format_section_header("Portfolio Overview"),
        "",
        f"USDT Balance: ${portfolio['usdt_balance']:,.2f}",
        f"Crypto Value: ${portfolio['crypto_value']:,.2f}",
        f"Total Equity: ${portfolio['total_equity']:,.2f}",
        f"Exposure: {portfolio['exposure_pct']:.1f}%",
        f"Open Positions: {portfolio['open_count']}",
    ]

    if portfolio["positions"]:
        pnl_sign = "+" if portfolio["total_unrealized_pnl"] >= 0 else ""
        lines.append(f"Unrealized P&L: {pnl_sign}{format_currency(portfolio['total_unrealized_pnl'])}")
        lines.append("")

        for p in portfolio["positions"]:
            pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
            lines.append(
                f"  {p['symbol']}: {p['quantity']:.6f} @ ${p['current_price']:,.2f} "
                f"= ${p['current_value']:,.2f} "
                f"({pnl_sign}{format_currency(p['unrealized_pnl'])}, {pnl_sign}{p['unrealized_pnl_pct']:.1f}%)"
            )

    print(truncate_for_telegram("\n".join(lines)))


def cmd_positions(args):
    from oakley_trading.common import truncate_for_telegram, format_currency, format_section_header
    from oakley_trading import engine
    from datetime import datetime

    symbol = None
    if args.symbol:
        symbol = args.symbol.upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

    result = engine.get_positions(symbol=symbol)
    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    positions = result["positions"]
    if not positions:
        msg = f"No open positions{f' for {symbol}' if symbol else ''}."
        print(msg)
        return

    lines = [format_section_header(f"Open Positions ({len(positions)})"), ""]

    for p in positions:
        pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
        age_ms = int(datetime.now().timestamp() * 1000) - p["timestamp"]
        age_hours = age_ms / (1000 * 60 * 60)
        if age_hours >= 24:
            age_str = f"{age_hours / 24:.1f}d"
        else:
            age_str = f"{age_hours:.1f}h"

        lines.append(f"{p['symbol']}")
        lines.append(f"  Qty: {p['quantity']:.6f}")
        lines.append(f"  Entry: ${p['entry_price']:,.2f} | Current: ${p['current_price']:,.2f}")
        lines.append(f"  Value: ${p['current_value']:,.2f}")
        lines.append(
            f"  P&L: {pnl_sign}{format_currency(p['unrealized_pnl'])} "
            f"({pnl_sign}{p['unrealized_pnl_pct']:.1f}%)"
        )
        if p.get("stop_loss"):
            lines.append(f"  Stop-loss: ${p['stop_loss']:,.2f}")
        if p.get("trailing_stop_price"):
            lines.append(f"  Trailing stop: ${p['trailing_stop_price']:,.2f}")
        lines.append(f"  Age: {age_str}")
        lines.append("")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_check_exits(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header
    from oakley_trading import risk

    result = risk.check_exit_conditions()

    lines = [
        format_section_header("Exit Check"),
        "",
        f"Positions checked: {result['checked']}",
        f"Positions closed: {result['closed']}",
    ]
    if result["errors"]:
        lines.append(f"Errors: {result['errors']}")

    for d in result["details"]:
        if d.get("error"):
            lines.append(f"  {d['symbol']}: ERROR - {d['error']}")
        elif d.get("closed"):
            lines.append(f"  {d['symbol']}: CLOSED ({d['reason']}) @ ${d['current_price']:,.2f}")
        else:
            parts = [f"${d['current_price']:,.2f}"]
            if d.get("highest_price_updated"):
                parts.append(f"new high ${d['highest_price_updated']:,.2f}")
            if d.get("trailing_stop_updated"):
                parts.append(f"trail ${d['trailing_stop_updated']:,.2f}")
            lines.append(f"  {d['symbol']}: OK - {', '.join(parts)}")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_risk(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header
    from oakley_trading import risk

    status = risk.get_risk_status()

    halt_str = "YES - TRADING HALTED" if status["halted"] else "No"

    lines = [
        format_section_header("Risk Status"),
        "",
        f"Halted: {halt_str}",
        f"Open positions: {status['open_positions']}",
        f"Total equity: ${status['total_equity']:,.2f}",
        f"Exposure: {status['exposure_pct']:.1f}% / {status['max_exposure_pct']:.0f}% max",
        "",
        f"Stop-loss type: {status['stop_loss_type']}",
        f"Default stop-loss: {status['default_stop_loss_pct']:.1f}%",
        f"Default trailing stop: {status['default_trailing_stop_pct']:.1f}%",
        f"Trailing stops enabled: {status['enable_trailing_stops']}",
    ]

    if status["positions"]:
        lines.append("")
        for p in status["positions"]:
            stop_info = ""
            if p.get("distance_to_stop_pct") is not None:
                stop_info = f" | {p['distance_to_stop_pct']:.1f}% to stop"
            lines.append(f"  {p['symbol']}: ${p['value']:,.2f}{stop_info}")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_halt(args):
    from oakley_trading import risk
    result = risk.halt()
    print(result["message"])


def cmd_resume(args):
    from oakley_trading import risk
    result = risk.resume()
    print(result["message"])


def cmd_performance(args):
    from oakley_trading.common import truncate_for_telegram, format_currency, format_section_header
    from oakley_trading import analytics

    period = args.period or "30d"
    symbol = None
    if args.symbol:
        symbol = args.symbol.upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

    perf = analytics.get_performance(period, symbol=symbol)

    title = f"Performance ({period})"
    if symbol:
        title += f" — {symbol}"
    lines = [format_section_header(title), ""]

    if perf["total_trades"] == 0:
        lines.append("No closed trades in this period.")
        print("\n".join(lines))
        return

    win_rate = f"{perf['win_rate']:.1f}%"
    pnl_sign = "+" if perf["total_pnl"] >= 0 else ""

    lines.extend([
        f"Trades: {perf['total_trades']} ({perf['winning']}W / {perf['losing']}L)",
        f"Win rate: {win_rate}",
        f"Total P&L: {pnl_sign}{format_currency(perf['total_pnl'])}",
        f"Total fees: {format_currency(perf['total_fees'])}",
        f"Net P&L: {pnl_sign}{format_currency(perf['net_pnl'])}",
        "",
        f"Avg win: {format_currency(perf['avg_win'])}",
        f"Avg loss: {format_currency(perf['avg_loss'])}",
        f"Profit factor: {perf['profit_factor']:.2f}",
    ])

    if perf["avg_holding_hours"] > 0:
        if perf["avg_holding_hours"] >= 24:
            lines.append(f"Avg hold: {perf['avg_holding_hours'] / 24:.1f} days")
        else:
            lines.append(f"Avg hold: {perf['avg_holding_hours']:.1f} hours")

    if perf["best_trade"]:
        lines.append(f"Best: {perf['best_trade']['symbol']} +{format_currency(perf['best_trade']['pnl'])} ({perf['best_trade']['pnl_percent']:+.1f}%)")
    if perf["worst_trade"]:
        lines.append(f"Worst: {perf['worst_trade']['symbol']} {format_currency(perf['worst_trade']['pnl'])} ({perf['worst_trade']['pnl_percent']:+.1f}%)")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_analytics(args):
    from oakley_trading.common import truncate_for_telegram, format_currency, format_section_header
    from oakley_trading import analytics

    period = args.period or "30d"
    data = analytics.get_full_analytics(period)
    perf = data["performance"]

    lines = [format_section_header(f"Analytics Dashboard ({period})"), ""]

    # Summary
    if perf["total_trades"] == 0:
        lines.append("No closed trades in this period.")
        print("\n".join(lines))
        return

    pnl_sign = "+" if perf["total_pnl"] >= 0 else ""
    lines.extend([
        f"Trades: {perf['total_trades']} ({perf['winning']}W / {perf['losing']}L) | Win rate: {perf['win_rate']:.1f}%",
        f"P&L: {pnl_sign}{format_currency(perf['total_pnl'])} (net: {pnl_sign}{format_currency(perf['net_pnl'])})",
        f"Profit factor: {perf['profit_factor']:.2f} | Sharpe: {data['sharpe_ratio']:.2f}",
    ])

    # Per-asset breakdown
    if data["asset_breakdown"]:
        lines.extend(["", format_section_header("By Asset")])
        for a in data["asset_breakdown"]:
            pnl_s = "+" if a["total_pnl"] >= 0 else ""
            lines.append(
                f"  {a['symbol']}: {a['trades']}t | "
                f"{a['win_rate']:.0f}% WR | "
                f"{pnl_s}{format_currency(a['total_pnl'])}"
            )

    # Exit reason breakdown
    if data["exit_reasons"]:
        lines.extend(["", format_section_header("By Exit Reason")])
        for e in data["exit_reasons"]:
            pnl_s = "+" if e["total_pnl"] >= 0 else ""
            lines.append(
                f"  {e['reason']}: {e['trades']}t | "
                f"{e['win_rate']:.0f}% WR | "
                f"{pnl_s}{format_currency(e['total_pnl'])}"
            )

    print(truncate_for_telegram("\n".join(lines)))


def cmd_reconcile(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header, format_currency
    from oakley_trading import reconciliation

    result = reconciliation.reconcile()

    if not result["success"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    lines = [
        format_section_header("Reconciliation Report"),
        "",
        f"Open trades checked: {result['open_trades_checked']}",
        f"Exchange assets checked: {result['exchange_assets_checked']}",
        f"Issues found: {result['total_issues']}",
    ]

    if not result["total_issues"]:
        lines.append("")
        lines.append("All clear — DB matches exchange.")
        print(truncate_for_telegram("\n".join(lines)))
        return

    if result["zombies"]:
        lines.extend(["", format_section_header("Zombies (DB open, no exchange balance)")])
        for z in result["zombies"]:
            lines.append(
                f"  {z['symbol']} (trade {z['trade_id']}): "
                f"DB qty {z['db_quantity']:.6f}, exchange {z['exchange_balance']:.6f}"
            )

    if result["orphans"]:
        lines.extend(["", format_section_header("Orphans (exchange balance, no DB record)")])
        for o in result["orphans"]:
            lines.append(
                f"  {o['asset']} ({o['symbol']}): "
                f"{o['exchange_balance']:.6f} (~{format_currency(o['estimated_value_usdt'])})"
            )

    if result["mismatches"]:
        lines.extend(["", format_section_header("Quantity Mismatches")])
        for m in result["mismatches"]:
            sign = "+" if m["difference"] >= 0 else ""
            lines.append(
                f"  {m['symbol']} (trade {m['trade_id']}): "
                f"DB {m['db_quantity']:.6f} vs exchange {m['exchange_balance']:.6f} "
                f"({sign}{m['difference_pct']:.1f}%)"
            )

    print(truncate_for_telegram("\n".join(lines)))


def cmd_recovery(args):
    from oakley_trading.common import truncate_for_telegram, format_section_header
    from oakley_trading import db as trade_db

    # --clear mode
    if args.clear is not None:
        success = trade_db.clear_recovery_item(args.clear)
        if success:
            print(f"Recovery item {args.clear} removed.")
        else:
            print(f"Error: Recovery item {args.clear} not found.", file=sys.stderr)
            sys.exit(1)
        return

    # --retry mode
    if args.retry:
        from oakley_trading import reconciliation
        result = reconciliation.retry_all_recovery()

        lines = [
            format_section_header("Recovery Retry"),
            "",
            f"Items processed: {result['total']}",
            f"Succeeded: {result['succeeded']}",
            f"Failed: {result['failed']}",
        ]

        if not result["total"]:
            lines.append("")
            lines.append("Recovery queue is empty.")

        for d in result["details"]:
            status = "OK" if d["result"]["success"] else f"FAILED — {d['result']['reason']}"
            lines.append(f"  #{d['id']} ({d['reason']}): {status}")

        print(truncate_for_telegram("\n".join(lines)))
        return

    # Default: list queue
    items = trade_db.get_recovery_queue()
    if not items:
        print("Recovery queue is empty.")
        return

    lines = [format_section_header(f"Recovery Queue ({len(items)} items)"), ""]
    for item in items:
        trade_data = item["trade_data"]
        trade_id = ""
        if isinstance(trade_data, dict):
            trade_id = trade_data.get("trade_id", "")
        lines.append(f"  #{item['id']} | {item['reason']}")
        if trade_id:
            lines.append(f"    Trade: {trade_id}")
        lines.append(f"    Created: {item['created_at']}")
        lines.append("")

    print(truncate_for_telegram("\n".join(lines)))


def cmd_config(args):
    from oakley_trading import db as trade_db

    if args.show:
        config = trade_db.get_all_config()
        if not config:
            print("No config overrides set. Using defaults.")
            from oakley_trading.common.config import Config
            defaults = {
                "default_allocation": str(Config.default_allocation),
                "default_stop_loss_pct": str(Config.default_stop_loss_pct),
                "default_trailing_stop_pct": str(Config.default_trailing_stop_pct),
                "max_portfolio_exposure": str(Config.max_portfolio_exposure),
                "risk_per_trade": str(Config.risk_per_trade),
                "min_trade_usdt": str(Config.min_trade_usdt),
                "stop_loss_type": str(Config.stop_loss_type),
                "stop_loss_atr_multiplier": str(Config.stop_loss_atr_multiplier),
                "enable_trailing_stops": str(Config.enable_trailing_stops),
            }
            lines = ["Defaults:"]
            for k, v in defaults.items():
                lines.append(f"  {k} = {v}")
            print("\n".join(lines))
            return

        lines = ["Config overrides:"]
        for k, v in config.items():
            lines.append(f"  {k} = {v}")
        print("\n".join(lines))
        return

    if args.set:
        for pair in args.set:
            if "=" not in pair:
                print(f"Error: Invalid format '{pair}'. Use KEY=VALUE.", file=sys.stderr)
                sys.exit(1)
            key, value = pair.split("=", 1)
            trade_db.set_config_value(key.strip(), value.strip())
            print(f"Set {key.strip()} = {value.strip()}")
        return

    print("Usage: oakley-trading config --show or config --set KEY=VALUE")


def main():
    parser = argparse.ArgumentParser(
        prog="oakley-trading",
        description="Oakley Trading — agent-directed crypto trading via Binance",
    )
    subparsers = parser.add_subparsers(dest="command")

    # setup
    setup_parser = subparsers.add_parser("setup", help="Configure Binance API credentials")
    setup_parser.add_argument("--api-key", required=True, help="Binance API key")
    setup_parser.add_argument("--api-secret", required=True, help="Binance API secret")

    # status
    subparsers.add_parser("status", help="Show version, connection health, portfolio summary")

    # account
    subparsers.add_parser("account", help="Show Binance account balances")

    # price
    price_parser = subparsers.add_parser("price", help="Get current price for a symbol")
    price_parser.add_argument("symbol", help="Trading pair (e.g. BTCUSDT or BTC)")

    # prices
    prices_parser = subparsers.add_parser("prices", help="Get prices for multiple symbols")
    prices_parser.add_argument("--symbols", default=None, help="Comma-separated symbols (e.g. BTC,ETH,SOL)")

    # candles
    candles_parser = subparsers.add_parser("candles", help="Get OHLCV candle data")
    candles_parser.add_argument("symbol", help="Trading pair (e.g. BTCUSDT or BTC)")
    candles_parser.add_argument("timeframe", help="Candle interval (1m,5m,15m,1h,4h,1d,...)")
    candles_parser.add_argument("--limit", type=int, default=20, help="Number of candles (default: 20)")

    # trades
    trades_parser = subparsers.add_parser("trades", help="Trade history")
    trades_parser.add_argument("--symbol", default=None, help="Filter by symbol")
    trades_parser.add_argument("--period", default="30d", help="Time period (1d, 7d, 30d, 90d, all)")
    trades_parser.add_argument("--limit", type=int, default=50, help="Max trades to show (default: 50)")

    # config
    config_parser = subparsers.add_parser("config", help="View/update trading config")
    config_parser.add_argument("--show", action="store_true", help="Show current config")
    config_parser.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="Set config values")

    # buy
    buy_parser = subparsers.add_parser("buy", help="Buy a crypto asset")
    buy_parser.add_argument("symbol", help="Trading pair (e.g. BTCUSDT or BTC)")
    buy_parser.add_argument("--allocation", type=float, default=None, help="Fraction of equity (e.g. 0.15)")
    buy_parser.add_argument("--stop-loss", type=float, default=None, help="Stop-loss percentage (e.g. 0.05)")
    buy_parser.add_argument("--trailing-stop", type=float, default=None, help="Trailing stop percentage (e.g. 0.03)")
    buy_parser.add_argument("--reason", default=None, help="Entry reason/type")
    buy_parser.add_argument("--dry-run", action="store_true", help="Simulate without placing order")

    # sell
    sell_parser = subparsers.add_parser("sell", help="Sell/close position by symbol")
    sell_parser.add_argument("symbol", help="Trading pair (e.g. BTCUSDT or BTC)")
    sell_parser.add_argument("--reason", default=None, help="Exit reason")
    sell_parser.add_argument("--dry-run", action="store_true", help="Simulate without placing order")

    # close
    close_parser = subparsers.add_parser("close", help="Close position by trade ID")
    close_parser.add_argument("trade_id", help="Trade ID to close")
    close_parser.add_argument("--reason", default=None, help="Exit reason")
    close_parser.add_argument("--dry-run", action="store_true", help="Simulate without placing order")

    # portfolio
    subparsers.add_parser("portfolio", help="Portfolio overview with all positions")

    # positions
    positions_parser = subparsers.add_parser("positions", help="Show open positions")
    positions_parser.add_argument("--symbol", default=None, help="Filter by symbol")

    # check-exits
    subparsers.add_parser("check-exits", help="Check stop-loss/trailing-stop, auto-close if triggered")

    # risk
    subparsers.add_parser("risk", help="Risk dashboard: exposure, positions, halt state")

    # performance
    perf_parser = subparsers.add_parser("performance", help="Performance metrics (win rate, P&L, profit factor)")
    perf_parser.add_argument("--period", default="30d", help="Time period (1d, 7d, 30d, 90d, all)")
    perf_parser.add_argument("--symbol", default=None, help="Filter by symbol")

    # analytics
    analytics_parser = subparsers.add_parser("analytics", help="Full analytics dashboard with per-asset breakdown")
    analytics_parser.add_argument("--period", default="30d", help="Time period (1d, 7d, 30d, 90d, all)")

    # halt
    subparsers.add_parser("halt", help="Halt all trading (emergency)")

    # resume
    subparsers.add_parser("resume", help="Resume trading after halt")

    # reconcile
    subparsers.add_parser("reconcile", help="Compare DB state vs Binance exchange state")

    # recovery
    recovery_parser = subparsers.add_parser("recovery", help="View/retry/clear recovery queue")
    recovery_parser.add_argument("--retry", action="store_true", help="Retry all failed items")
    recovery_parser.add_argument("--clear", type=int, default=None, metavar="ID", help="Remove item by ID")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "account": cmd_account,
        "price": cmd_price,
        "prices": cmd_prices,
        "candles": cmd_candles,
        "trades": cmd_trades,
        "config": cmd_config,
        "buy": cmd_buy,
        "sell": cmd_sell,
        "close": cmd_close,
        "portfolio": cmd_portfolio,
        "positions": cmd_positions,
        "check-exits": cmd_check_exits,
        "risk": cmd_risk,
        "performance": cmd_performance,
        "analytics": cmd_analytics,
        "halt": cmd_halt,
        "resume": cmd_resume,
        "reconcile": cmd_reconcile,
        "recovery": cmd_recovery,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
