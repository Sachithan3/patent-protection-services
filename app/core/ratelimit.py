"""Token-bucket rate limiting for outbound provider calls (spec sections 7.3, 14.2).

Clock and sleeper are injectable so tests are deterministic without real delays.
One bucket per provider, sized from that provider's documented limits.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

Clock = Callable[[], float]
AsyncSleeper = Callable[[float], Awaitable[None]]


class TokenBucket:
    """Classic token bucket: `rate_per_second` refill, `capacity` burst size."""

    def __init__(
        self,
        rate_per_second: float,
        capacity: float,
        *,
        clock: Clock = time.monotonic,
        sleeper: AsyncSleeper = asyncio.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._rate = rate_per_second
        self._capacity = capacity
        self._clock = clock
        self._sleeper = sleeper
        self._tokens = capacity
        self._last_refill = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def try_acquire(self) -> bool:
        """Take one token if one is available without waiting."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def wait_time(self) -> float:
        """Seconds until one token is available; 0.0 when one is available now."""
        self._refill()
        deficit = 1.0 - self._tokens
        return max(0.0, deficit / self._rate)

    async def acquire(self) -> None:
        """Wait until a token is available, then take it."""
        while True:
            delay = self.wait_time()
            if delay == 0.0:
                self.try_acquire()
                return
            await self._sleeper(delay)
