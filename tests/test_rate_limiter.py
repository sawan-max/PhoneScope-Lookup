import pytest

from rate_limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock)
    assert all(limiter.check(1).allowed for _ in range(3))
    blocked = limiter.check(1)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 60


def test_window_expires():
    clock = FakeClock()
    limiter = RateLimiter(2, 60, clock)
    limiter.check(1)
    limiter.check(1)
    assert not limiter.check(1).allowed
    clock.now += 61
    assert limiter.check(1).allowed


def test_retry_after_counts_down():
    clock = FakeClock()
    limiter = RateLimiter(1, 60, clock)
    limiter.check(1)
    clock.now += 45
    assert limiter.check(1).retry_after_seconds == 15


def test_users_are_independent():
    limiter = RateLimiter(1, 60, FakeClock())
    assert limiter.check(1).allowed
    assert not limiter.check(1).allowed
    assert limiter.check(2).allowed


def test_reset_clears_user():
    limiter = RateLimiter(1, 60, FakeClock())
    limiter.check(1)
    limiter.reset(1)
    assert limiter.check(1).allowed


@pytest.mark.parametrize("max_requests,window", [(0, 60), (-1, 60), (1, 0), (1, -5)])
def test_invalid_configuration(max_requests, window):
    with pytest.raises(ValueError):
        RateLimiter(max_requests, window)
