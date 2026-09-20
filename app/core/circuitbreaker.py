"""Per-provider circuit breaker (spec section 7.3).

After `failure_threshold` consecutive failures the circuit opens and calls are
skipped (providers fail fast, the registry treats it as a warning). After
`cooldown_seconds` the circuit half-opens: one trial call is allowed; failure
re-opens with a fresh cooldown, success closes.
"""

import time
from collections.abc import Callable

Clock = Callable[[], float]


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the circuit is open."""


class CircuitBreaker:
    """Consecutive-failure counter with an open/half-open/closed state machine."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        """One of 'closed', 'open', or 'half_open' (exposed for the health endpoint)."""
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._cooldown:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """Whether a call may proceed right now."""
        return self.state != "open"

    def check(self) -> None:
        """Raise CircuitOpenError unless a call may proceed now."""
        if not self.allow():
            raise CircuitOpenError("circuit is open; call skipped")

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._opened_at = self._clock()
