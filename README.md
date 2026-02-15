# oakley-trading

Agent-directed crypto trading CLI and [OpenClaw](https://openclaw.dev) skill for Binance. Execute trades, manage positions, enforce risk controls (stop-loss, trailing stops, exposure caps), review analytics, and reconcile with the exchange.

The agent researches and decides what to trade (using oakley-analyst); this skill provides the execution layer. All trade commands support `--dry-run` for safe previewing. Output goes to stdout for OpenClaw to deliver via Telegram.

## Install

```bash
pipx install . --force
```

## Setup

Store your Binance API credentials:

```bash
oakley-trading setup --api-key KEY --api-secret SECRET
```

Verify the connection:

```bash
oakley-trading status
```

Credentials are stored in `~/.oakley-trading/data/config.json`.

## Commands

| Command | Description |
|---------|-------------|
| `setup` | Configure Binance API credentials |
| `status` | Version, connection health, portfolio summary |
| `account` | Binance account balances |
| `price` | Current price for a symbol |
| `prices` | Multiple/all tracked prices |
| `candles` | OHLCV candle data |
| `buy` | Open a long position (market order) |
| `sell` | Close position by symbol |
| `close` | Close position by trade ID |
| `portfolio` | Full portfolio overview with unrealized P&L |
| `positions` | Open position details |
| `trades` | Trade history with period/symbol filters |
| `performance` | Win rate, P&L, profit factor, Sharpe |
| `analytics` | Full dashboard with per-asset and exit reason breakdowns |
| `check-exits` | Enforce stop-loss/trailing stops (cron target) |
| `risk` | Risk dashboard: exposure, stops, halt state |
| `halt` / `resume` | Emergency trading halt / resume |
| `config` | View/update trading parameters |
| `reconcile` | Compare DB state vs Binance holdings |
| `recovery` | View/retry/clear failed DB operation queue |

Run `oakley-trading <command> --help` for detailed usage.

## Usage

```bash
# Check portfolio state
oakley-trading portfolio

# Dry-run a buy
oakley-trading buy BTC --allocation 0.15 --reason "Thesis from research" --dry-run

# Execute the trade
oakley-trading buy BTC --allocation 0.15 --reason "Thesis from research"

# Close a position
oakley-trading sell BTC --reason "Target reached"

# Performance review
oakley-trading performance --period 30d
oakley-trading analytics --period 7d

# Risk management
oakley-trading risk
oakley-trading check-exits
oakley-trading halt

# Adjust config
oakley-trading config --show
oakley-trading config --set default_allocation=0.10 default_stop_loss_pct=0.03

# Reconciliation
oakley-trading reconcile
oakley-trading recovery --retry
```

## Architecture

```
oakley_trading/
├── cli.py               # argparse dispatcher (21 commands)
├── auth.py              # Binance credential management
├── client.py            # python-binance wrapper with rate limiting
├── data_service.py      # Market data: prices, candles, account, exchange info, ATR, order execution
├── db.py                # SQLite: schema, trade CRUD, config CRUD, recovery queue
├── engine.py            # Trading engine: buy/sell/close, portfolio, positions, fee calc, locks
├── risk.py              # Risk management: check-exits, trailing stops, halt/resume, dashboard
├── analytics.py         # Performance: win rate, P&L, profit factor, Sharpe, per-asset, exit reasons
├── reconciliation.py    # Zombie/orphan/mismatch detection vs Binance, recovery retry
└── common/
    ├── config.py        # Paths, constants, trading defaults
    ├── cache.py         # File-based JSON cache with TTL + 24hr stale fallback
    ├── rate_limiter.py  # Token-bucket rate limiter
    └── formatting.py    # Telegram-safe output, AEDT timezone, number formatting
```

### Data Storage

```
~/.oakley-trading/data/
├── trading.db            # SQLite (WAL mode) — trades, config, recovery queue
├── config.json           # Binance API credentials
├── cache/                # API response cache (auto-managed TTL)
└── locks/                # Per-symbol close operation locks
```

Set `OAKLEY_TRADING_DATA_DIR` to override the default data location.

## Cron

Stop-loss and trailing stop enforcement runs every 5 minutes:

```
*/5 * * * * /home/oakley/.local/bin/oakley-trading check-exits
```

## Dependencies

- **python-binance** >= 1.0.19 — Binance REST API client
- **pytz** >= 2023.3 — timezone handling

## Deployment

```bash
# Push changes, then on the device:
ssh oakley@bot.oakroad
cd /home/oakley/.openclaw/workspace/skills/oakley-trading
git pull
pipx install . --force
```

## License

Private skill. Not for redistribution.
