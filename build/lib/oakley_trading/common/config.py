import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("OAKLEY_TRADING_DATA_DIR", Path.home() / ".oakley-trading" / "data"))
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "trading.db"
LOCK_DIR = DATA_DIR / "locks"
CONFIG_PATH = DATA_DIR / "config.json"

CACHE_TTL = {
    "price": 15,           # 15 seconds — REST price freshness
    "prices": 15,
    "candles": 60,         # 1 minute
    "exchange_info": 3600, # 1 hour
    "account": 10,         # 10 seconds
}

STALE_CACHE_MAX_AGE = 86400  # 24 hours fallback

# Binance rate limits (conservative)
BINANCE_RATE_LIMIT_CALLS = 10
BINANCE_RATE_LIMIT_PERIOD = 1  # 10 req/sec

TELEGRAM_MAX_LENGTH = 4096

TIMEZONE = "Australia/Sydney"

REQUEST_TIMEOUT = 10  # seconds

# Trading defaults
DEFAULT_ALLOCATION = 0.15          # 15% of equity per trade
DEFAULT_STOP_LOSS_PCT = 0.05       # 5% stop-loss
DEFAULT_TRAILING_STOP_PCT = 0.03   # 3% trailing stop
MAX_PORTFOLIO_EXPOSURE = 0.95      # 95% max exposure
MAX_CAPITAL_AT_RISK = 999999       # No cap by default
RISK_PER_TRADE = 0.98              # 98% of allocation (2% buffer)
MIN_TRADE_USDT = 10                # Binance minimum notional
CASH_BUFFER = 0.01                 # 1% cash buffer when constrained
STOP_LOSS_TYPE = "FIXED"           # FIXED or ATR
STOP_LOSS_ATR_MULTIPLIER = 1.5     # ATR multiplier for ATR-based stop-loss
ENABLE_TRAILING_STOPS = True       # Whether check-exits enforces trailing stops


class Config:
    """Central access point for all configuration."""

    package_dir = _PACKAGE_DIR
    data_dir = DATA_DIR
    cache_dir = CACHE_DIR
    db_path = DB_PATH
    lock_dir = LOCK_DIR
    config_path = CONFIG_PATH

    cache_ttl = CACHE_TTL
    stale_cache_max_age = STALE_CACHE_MAX_AGE

    binance_rate_limit_calls = BINANCE_RATE_LIMIT_CALLS
    binance_rate_limit_period = BINANCE_RATE_LIMIT_PERIOD

    telegram_max_length = TELEGRAM_MAX_LENGTH
    timezone = TIMEZONE
    request_timeout = REQUEST_TIMEOUT

    # Trading defaults
    default_allocation = DEFAULT_ALLOCATION
    default_stop_loss_pct = DEFAULT_STOP_LOSS_PCT
    default_trailing_stop_pct = DEFAULT_TRAILING_STOP_PCT
    max_portfolio_exposure = MAX_PORTFOLIO_EXPOSURE
    max_capital_at_risk = MAX_CAPITAL_AT_RISK
    risk_per_trade = RISK_PER_TRADE
    min_trade_usdt = MIN_TRADE_USDT
    cash_buffer = CASH_BUFFER
    stop_loss_type = STOP_LOSS_TYPE
    stop_loss_atr_multiplier = STOP_LOSS_ATR_MULTIPLIER
    enable_trailing_stops = ENABLE_TRAILING_STOPS

    @classmethod
    def ensure_dirs(cls):
        cls.data_dir.mkdir(parents=True, exist_ok=True)
        cls.cache_dir.mkdir(parents=True, exist_ok=True)
        cls.lock_dir.mkdir(parents=True, exist_ok=True)
