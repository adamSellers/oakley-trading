---
name: oakley-trading
description: "Agent-directed crypto trading skill for Binance. Execute trades, manage positions, enforce risk controls (stop-loss, trailing stops, exposure caps), review analytics, and reconcile with the exchange. The agent makes trading decisions; this skill provides the execution layer."
---

# Oakley Trading Skill

Agent-directed crypto trading via Binance. The agent researches and decides what to trade (using oakley-analyst); this skill executes, monitors, and manages positions. All trade commands support `--dry-run` for safe previewing before real execution.

## When to Use

- User asks to buy or sell crypto
- User asks to check their trading portfolio or open positions
- User asks about trading performance, win rate, or P&L
- User asks to set or adjust stop-losses, trailing stops, or risk parameters
- User asks to check or manage risk exposure
- User asks to halt or resume trading
- User asks to reconcile positions with the exchange
- User asks for price data or candle charts for a crypto asset
- Cron-triggered `check-exits` for automated stop-loss/trailing-stop enforcement

## When NOT to Use

- Research, analysis, or deep dives on a topic -> use **oakley-analyst**
- Content about crypto for X/Twitter -> use **oakley-x**
- The agent should NOT generate trading signals or indicators — the agent IS the signal generator

## Setup

One-time credential configuration:

```bash
exec oakley-trading setup --api-key KEY --api-secret SECRET
```

Verify connection:

```bash
exec oakley-trading status
```

## Commands

Output goes to stdout — use `message` to deliver to Telegram.

All trade commands (`buy`, `sell`, `close`) support `--dry-run` — shows what would happen without executing. **Always use `--dry-run` first** unless the user has explicitly confirmed they want to execute.

### status — Health Check

```bash
exec oakley-trading status
```

Shows version, Binance connection health, USDT balance, open position count, total trades, and halt state.

**When to use:** Quick overview of system state. Run this before trading sessions to confirm connectivity.

### account — Binance Balances

```bash
exec oakley-trading account
```

Shows all non-zero balances: USDT (free/locked), BNB, and any crypto holdings.

**When to use:** User asks about their exchange balances or available capital.

### price — Current Price

```bash
exec oakley-trading price <SYMBOL>
```

- `<SYMBOL>` — Trading pair (e.g. `BTCUSDT` or `BTC` — USDT suffix auto-appended)

**Example:**

```bash
exec oakley-trading price BTC
```

**When to use:** Quick price check for a single asset.

### prices — Multiple Prices

```bash
exec oakley-trading prices [--symbols SYM1,SYM2,...]
```

- `--symbols` — Comma-separated symbols (e.g. `BTC,ETH,SOL`). Omit for all tracked.

**Example:**

```bash
exec oakley-trading prices --symbols BTC,ETH,SOL,AVAX
```

**When to use:** Price comparison across multiple assets.

### candles — OHLCV Candle Data

```bash
exec oakley-trading candles <SYMBOL> <TIMEFRAME> [--limit N]
```

- `<SYMBOL>` — Trading pair
- `<TIMEFRAME>` — Candle interval: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, `1w`, etc.
- `--limit` — Number of candles (default: 20)

**Example:**

```bash
exec oakley-trading candles BTC 4h --limit 10
```

**When to use:** User asks for price action, chart data, or you need candle data to inform a trading decision.

### buy — Open a Position

```bash
exec oakley-trading buy <SYMBOL> [--allocation PCT] [--stop-loss PCT] [--trailing-stop PCT] [--reason "..."] [--dry-run]
```

- `<SYMBOL>` — Trading pair (e.g. `BTC` or `BTCUSDT`)
- `--allocation` — Fraction of equity to allocate (e.g. `0.15` for 15%). Default: 0.15
- `--stop-loss` — Stop-loss percentage (e.g. `0.05` for 5%). Default: 0.05
- `--trailing-stop` — Trailing stop percentage (e.g. `0.03` for 3%). Default: 0.03
- `--reason` — Entry reason/thesis (stored in trade record for audit)
- `--dry-run` — Simulate without placing a real order

**Examples:**

```bash
# Preview a trade
exec oakley-trading buy BTC --allocation 0.15 --reason "Strong support at 60k, RSI oversold" --dry-run

# Execute the trade
exec oakley-trading buy BTC --allocation 0.15 --reason "Strong support at 60k, RSI oversold"

# Smaller position with tighter stops
exec oakley-trading buy ETH --allocation 0.10 --stop-loss 0.03 --trailing-stop 0.02 --reason "ETH/BTC ratio reversal"
```

**When to use:** User asks to buy, enter, or open a long position. Always dry-run first unless explicitly told to execute.

**Pre-trade checks (automatic):**
1. Trading not halted
2. No existing open position for this symbol
3. Portfolio exposure below 95% cap
4. Position size meets $10 minimum notional
5. Sufficient USDT balance (with 1% cash buffer)

### sell — Close Position by Symbol

```bash
exec oakley-trading sell <SYMBOL> [--reason "..."] [--dry-run]
```

- `<SYMBOL>` — Trading pair to sell
- `--reason` — Exit reason (e.g. `MANUAL`, `TAKE_PROFIT`, `THESIS_INVALIDATED`)
- `--dry-run` — Simulate without placing a real order

**Example:**

```bash
exec oakley-trading sell BTC --reason "Target reached, taking profit"
```

**When to use:** User asks to sell, exit, or close a position by symbol name.

### close — Close Position by Trade ID

```bash
exec oakley-trading close <TRADE_ID> [--reason "..."] [--dry-run]
```

- `<TRADE_ID>` — Trade ID from the trades/positions output
- `--reason` — Exit reason

**When to use:** When multiple positions might exist or you need to close a specific trade by ID.

### portfolio — Portfolio Overview

```bash
exec oakley-trading portfolio
```

Shows USDT balance, crypto value, total equity, exposure %, open position count, unrealized P&L, and per-position details (quantity, current price, current value, unrealized P&L).

**When to use:** User asks for a portfolio overview, total value, or wants to see all positions at a glance.

### positions — Open Position Details

```bash
exec oakley-trading positions [--symbol SYM]
```

- `--symbol` — Filter by symbol (optional)

Shows detailed info per position: quantity, entry/current price, value, unrealized P&L, stop-loss, trailing stop, and age.

**When to use:** User asks for details on open positions. More detailed than `portfolio`.

### trades — Trade History

```bash
exec oakley-trading trades [--symbol SYM] [--period PERIOD] [--limit N]
```

- `--symbol` — Filter by symbol
- `--period` — Time period: `1d`, `7d`, `30d`, `90d`, `all` (default: `30d`)
- `--limit` — Max trades to show (default: 50)

**Example:**

```bash
exec oakley-trading trades --period 7d
exec oakley-trading trades --symbol BTC --period all
```

**When to use:** User asks about trade history, past trades, or wants to review what happened.

### performance — Performance Metrics

```bash
exec oakley-trading performance [--period PERIOD] [--symbol SYM]
```

- `--period` — Time period: `1d`, `7d`, `30d`, `90d`, `all` (default: `30d`)
- `--symbol` — Filter by symbol

Shows: trade count (wins/losses), win rate, total P&L, fees, net P&L, avg win/loss, profit factor, avg holding time, best/worst trade.

**Example:**

```bash
exec oakley-trading performance --period 7d
exec oakley-trading performance --symbol ETH --period 90d
```

**When to use:** User asks about trading performance, win rate, P&L, or how well trades are doing.

### analytics — Full Analytics Dashboard

```bash
exec oakley-trading analytics [--period PERIOD]
```

- `--period` — Time period (default: `30d`)

Shows performance summary plus Sharpe ratio, per-asset breakdown (trades, win rate, P&L per symbol), and exit reason breakdown.

**When to use:** User asks for a comprehensive analytics overview or wants to see breakdowns by asset or exit type.

### risk — Risk Dashboard

```bash
exec oakley-trading risk
```

Shows halt state, open position count, total equity, current vs max exposure, stop-loss configuration, trailing stop settings, and per-position distance to stop.

**When to use:** User asks about risk exposure, stop-loss settings, or current risk state.

### check-exits — Enforce Stop-Loss/Trailing Stops

```bash
exec oakley-trading check-exits
```

For each open position: fetches current price, checks stop-loss breach, updates trailing stop high-water mark and ratchets trailing stop up, auto-closes positions that breach stops. Reports summary of actions taken.

**When to use:** Primarily run by cron (every 5 minutes). Also run manually when the user asks to check if any stops should trigger.

### halt — Emergency Trading Halt

```bash
exec oakley-trading halt
```

Halts all new buys. Sells, closes, and check-exits still work (you need to be able to exit positions during a halt).

**When to use:** User asks to stop trading, pause, or there's an emergency. Also use proactively if market conditions are extreme.

### resume — Resume Trading

```bash
exec oakley-trading resume
```

Lifts the trading halt, allowing buys again.

**When to use:** User asks to resume trading after a halt.

### config — View/Update Trading Config

```bash
# Show current config (overrides + defaults)
exec oakley-trading config --show

# Set a config override
exec oakley-trading config --set KEY=VALUE [KEY2=VALUE2 ...]
```

**Configurable settings:**
- `default_allocation` — Default position size as fraction of equity (default: 0.15)
- `default_stop_loss_pct` — Default stop-loss percentage (default: 0.05)
- `default_trailing_stop_pct` — Default trailing stop percentage (default: 0.03)
- `max_portfolio_exposure` — Max portfolio exposure cap (default: 0.95)
- `risk_per_trade` — Fraction of allocation to use (default: 0.98)
- `min_trade_usdt` — Minimum trade size in USDT (default: 10)
- `stop_loss_type` — `FIXED` or `ATR` (default: FIXED)
- `stop_loss_atr_multiplier` — ATR multiplier for ATR-based stops (default: 1.5)
- `enable_trailing_stops` — Whether trailing stops are enforced (default: true)

**Example:**

```bash
exec oakley-trading config --set default_allocation=0.10 default_stop_loss_pct=0.03
```

**When to use:** User asks to adjust trading parameters, position sizing, or stop-loss defaults.

### reconcile — Compare DB vs Exchange

```bash
exec oakley-trading reconcile
```

Compares the trade database against actual Binance holdings. Detects:
- **Zombies** — DB says position is open, but exchange has no balance
- **Orphans** — Exchange has a balance, but DB has no open trade (ignores USDT, BNB, and balances under $1)
- **Mismatches** — DB quantity differs from exchange balance by more than 1%

**When to use:** If something seems off, or periodically to verify DB accuracy. This is diagnostic only — it reports issues but does not auto-fix.

### recovery — Manage Recovery Queue

```bash
# List pending recovery items
exec oakley-trading recovery

# Retry all failed items
exec oakley-trading recovery --retry

# Remove a specific item
exec oakley-trading recovery --clear ID
```

The recovery queue holds failed database writes (when an exchange order succeeded but the DB write failed). Retry replays only the DB write — the exchange order already executed.

**When to use:** After `reconcile` detects issues, or if a trade command reported a DB write failure.

## Trading Workflows

### Trade Execution Workflow

Use when the user asks to enter a new position.

**Steps:**

1. **Research** — Use oakley-analyst to research the asset. Check saved knowledge, run web searches, review fundamentals.

2. **Check portfolio state** — Review current exposure and available capital:
   ```bash
   exec oakley-trading portfolio
   ```

3. **Check price** — Get current market price:
   ```bash
   exec oakley-trading price BTC
   ```

4. **Dry-run** — Preview the trade with the agent's thesis as the reason:
   ```bash
   exec oakley-trading buy BTC --allocation 0.15 --reason "Thesis from research" --dry-run
   ```

5. **Confirm with user** — Present the dry-run results. Only execute after explicit user approval.

6. **Execute** — Place the real order:
   ```bash
   exec oakley-trading buy BTC --allocation 0.15 --reason "Thesis from research"
   ```

7. **Verify** — Confirm the position is open:
   ```bash
   exec oakley-trading positions --symbol BTC
   ```

### Position Exit Workflow

Use when the user asks to close a position or take profit.

**Steps:**

1. **Review position** — Check current state:
   ```bash
   exec oakley-trading positions --symbol BTC
   ```

2. **Evaluate** — Consider unrealized P&L, original thesis, and current market conditions.

3. **Close** — Exit the position with reason:
   ```bash
   exec oakley-trading sell BTC --reason "Target reached, +12% gain"
   ```

4. **Review** — Check updated portfolio:
   ```bash
   exec oakley-trading portfolio
   ```

### Risk Review Workflow

Use when the user asks about risk, or proactively during volatile markets.

**Steps:**

1. **Check risk dashboard** — Current exposure and stop distances:
   ```bash
   exec oakley-trading risk
   ```

2. **Check exits** — See if any stops should trigger:
   ```bash
   exec oakley-trading check-exits
   ```

3. **Review positions** — Detailed position state:
   ```bash
   exec oakley-trading positions
   ```

4. **Adjust if needed** — Tighten stops, halt trading, or close positions:
   ```bash
   exec oakley-trading config --set default_stop_loss_pct=0.03
   exec oakley-trading halt
   ```

### Portfolio Review Workflow

Use when the user asks for a comprehensive trading review.

**Steps:**

1. **Portfolio overview**:
   ```bash
   exec oakley-trading portfolio
   ```

2. **Performance metrics**:
   ```bash
   exec oakley-trading performance --period 30d
   ```

3. **Full analytics** (if enough trade history):
   ```bash
   exec oakley-trading analytics --period 30d
   ```

4. **Reconcile** — Verify DB matches exchange:
   ```bash
   exec oakley-trading reconcile
   ```

5. **Synthesise** — Present findings to the user with recommendations (adjust allocation, tighten stops, review losing patterns, etc.)

### Reconciliation Workflow

Use periodically or when something seems off.

**Steps:**

1. **Run reconcile**:
   ```bash
   exec oakley-trading reconcile
   ```

2. **If issues found:**
   - **Zombies** — Position may have been sold directly on exchange. Investigate and consider manually closing the DB record.
   - **Orphans** — Crypto bought outside this system. Not necessarily a problem.
   - **Mismatches** — Partial fills or rounding. Usually minor.

3. **Check recovery queue**:
   ```bash
   exec oakley-trading recovery
   ```

4. **Retry if needed**:
   ```bash
   exec oakley-trading recovery --retry
   ```

## Cron Jobs

### Check Exits (every 5 minutes)

Schedule: `*/5 * * * *` (Australia/Sydney timezone)

```bash
exec oakley-trading check-exits
```

Automatically enforces stop-loss and trailing stop levels for all open positions. If a position is closed, deliver the output via `message` so the user is notified. If all positions are OK (no closes), no message is needed.

## Error Handling

- **"Authentication failed" / "Connection test: FAILED"** — Run `oakley-trading setup` to reconfigure Binance API credentials
- **"Buy refused: Trading is halted"** — Run `oakley-trading resume` if the user wants to trade again
- **"Buy refused: Existing open position"** — Already have an open position for that symbol. Use `sell` first to close it.
- **"Buy refused: Portfolio exposure exceeds maximum"** — Too much capital deployed. Close some positions first.
- **"Buy refused: Position size below minimum"** — Allocation too small or insufficient balance. Increase allocation or deposit more USDT.
- **"Sell failed: No open position"** — No open trade for that symbol. Check `positions` to verify.
- **Network/timeout errors** — Retry once. If it fails again, inform the user. Do NOT retry a trade order — it may have executed on the exchange even if the response was lost.
- **DB write failure after successful order** — The trade executed on Binance but the local DB write failed. The trade is recorded in the recovery queue. Run `recovery --retry` to replay the DB write.
- If a command returns an error, do NOT retry trade commands (`buy`, `sell`, `close`) more than once — the order may have already executed on the exchange.

## Data Storage

- **Database**: `~/.oakley-trading/data/trading.db` — SQLite (WAL mode). All trade records, config overrides, recovery queue.
- **Cache**: `~/.oakley-trading/data/cache/` — API response cache (auto-managed, 15s for prices, 60s for candles, 1hr for exchange info)
- **Credentials**: `~/.oakley-trading/data/config.json` — Binance API key/secret
- **Locks**: `~/.oakley-trading/data/locks/` — File-based close operation locks (auto-cleaned after 5 minutes)

Set `OAKLEY_TRADING_DATA_DIR` to override the default data location.

## Notes

- **Agent-directed** — This skill executes trades, it does not generate signals or make trading decisions. The agent researches via oakley-analyst and decides; this skill is the execution layer.
- **The `--reason` flag is important** — Always include a reason when buying or selling. This captures the agent's thesis in the trade record for later audit and analytics.
- **Dry-run first** — For any buy/sell/close, prefer `--dry-run` first unless the user has explicitly confirmed.
- **USDT pairs only** — All symbols are traded against USDT (e.g. BTCUSDT, ETHUSDT).
- **LONG only** — Only long positions are supported. No short selling.
- **Market orders** — All orders are market orders for immediate execution.
- **Telegram 4096 char limit** — All output is auto-truncated to fit.
- **Rate limiting** — Binance API calls are rate-limited (10 req/sec). Do not call price/account commands in rapid loops.
- **File-based locks** — Close operations use per-symbol file locks to prevent double-closes. Locks auto-expire after 5 minutes.
- **Config overrides** — DB config values override defaults. Use `config --set` to adjust without code changes.
