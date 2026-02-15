import time

from .config import Config


class RateLimiter:
    """Token-bucket rate limiter for API calls."""

    def __init__(
        self,
        max_calls: int = Config.binance_rate_limit_calls,
        period: float = Config.binance_rate_limit_period,
    ):
        self.max_calls = max_calls
        self.period = period
        self.calls: list[float] = []

    def acquire(self) -> None:
        """Block until a call slot is available."""
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period]

        if len(self.calls) >= self.max_calls:
            oldest = self.calls[0]
            sleep_time = self.period - (now - oldest)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.calls = [t for t in self.calls if time.time() - t < self.period]

        self.calls.append(time.time())
