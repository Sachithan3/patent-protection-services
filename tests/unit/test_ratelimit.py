"""Deterministic unit tests for the token bucket (no real sleeps)."""

import pytest

from app.core.ratelimit import TokenBucket


class FakeClock:
    """Manual clock the tests advance by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_try_acquire_allows_burst_up_to_capacity() -> None:
    bucket = TokenBucket(rate_per_second=10.0, capacity=2.0)

    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False


async def test_refill_restores_tokens_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=1.0, capacity=1.0, clock=clock)

    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False

    clock.now += 1.0
    assert bucket.try_acquire() is True


async def test_acquire_waits_until_a_token_refills() -> None:
    clock = FakeClock()

    async def advance(seconds: float) -> None:
        clock.now += seconds

    bucket = TokenBucket(rate_per_second=1.0, capacity=1.0, clock=clock, sleeper=advance)
    await bucket.acquire()  # consumes the initial token
    await bucket.acquire()  # must loop through the fake sleeper until refill

    assert bucket.wait_time() == pytest.approx(1.0)


async def test_wait_time_is_zero_when_token_available() -> None:
    bucket = TokenBucket(rate_per_second=5.0, capacity=3.0)
    assert bucket.wait_time() == 0.0


@pytest.mark.parametrize(("rate", "capacity"), [(0.0, 1.0), (-1.0, 1.0), (1.0, 0.0), (1.0, -2.0)])
def test_rejects_non_positive_rate_or_capacity(rate: float, capacity: float) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_second=rate, capacity=capacity)
