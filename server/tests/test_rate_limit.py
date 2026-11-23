"""Unit tests for sliding-window and in-flight capacity gates (no HTTP)."""

import pytest

from app.rate_limit import InFlightGate, SuggestRateLimiter
from helpers import FrozenClock


def test_rate_limiter_admits_up_to_max_and_expires_sliding_window() -> None:
    clock = FrozenClock(10.0)
    limiter = SuggestRateLimiter(2, 60, clock)

    first = limiter.allow()
    clock.now = 25.0
    second = limiter.allow()
    assert first.token is not None and first.retry_after is None
    assert second.token is not None and second.retry_after is None

    blocked = limiter.allow()
    assert blocked.token is None
    assert blocked.retry_after == 45

    # Just before the first hit's 60s window expires, still blocked with ceil → 1.
    clock.now = 69.99
    near_end = limiter.allow()
    assert near_end.token is None
    assert near_end.retry_after == 1

    # At exact cutoff (now - window == 10.0), first expires while second (at 25.0) stays.
    clock.now = 70.0
    third = limiter.allow()
    assert third.token is not None and third.retry_after is None
    fourth = limiter.allow()
    assert fourth.token is None
    assert fourth.retry_after == 15


def test_rate_limiter_retry_after_ceiling_rounding() -> None:
    clock = FrozenClock(0.0)
    limiter = SuggestRateLimiter(1, 60, clock)
    assert limiter.allow().retry_after is None

    assert limiter.allow().retry_after == 60
    clock.now = 0.1
    assert limiter.allow().retry_after == 60
    clock.now = 1.0
    assert limiter.allow().retry_after == 59
    clock.now = 59.01
    assert limiter.allow().retry_after == 1
    clock.now = 59.999
    assert limiter.allow().retry_after == 1


def test_rate_limiter_release_only_refunds_matching_token() -> None:
    """Concurrent hits: unknown/double release is safe and never pops a sibling hit."""
    clock = FrozenClock(0.0)
    limiter = SuggestRateLimiter(2, 60, clock)
    a = limiter.allow()
    clock.now = 10.0
    b = limiter.allow()
    assert a.token is not None and b.token is not None

    limiter.release(object())
    limiter.release(None)
    assert limiter.allow().retry_after == 50  # oldest is still 'a' at t=0.0

    limiter.release(a.token)
    limiter.release(a.token)  # double release is a no-op; 'b' at t=10.0 remains
    c = limiter.allow()
    assert c.token is not None and c.retry_after is None
    # Active hits are 'b' (t=10) and 'c' (t=10), so Retry-After at t=10 is full 60s.
    assert limiter.allow().retry_after == 60

    limiter.release(b.token)
    assert limiter.allow().retry_after is None


def test_in_flight_rejects_non_positive_max() -> None:
    with pytest.raises(ValueError, match="max_in_flight"):
        InFlightGate(0)


def test_in_flight_admits_up_to_max() -> None:
    gate = InFlightGate(2)
    first = gate.acquire()
    second = gate.acquire()
    assert first.retry_after is None and first.token is not None
    assert second.retry_after is None and second.token is not None
    blocked = gate.acquire()
    assert blocked.token is None
    assert blocked.retry_after == 1


def test_in_flight_release_none_is_noop() -> None:
    gate = InFlightGate(1)
    held = gate.acquire()
    assert held.token is not None
    gate.release(None)
    assert gate.acquire().token is None
    gate.release(held.token)
    assert gate.acquire().retry_after is None


def test_in_flight_release_only_frees_matching_token() -> None:
    """Under max>1, unknown/double release must not steal a sibling's slot."""
    gate = InFlightGate(2)
    a = gate.acquire()
    b = gate.acquire()
    assert a.token is not None and b.token is not None
    gate.release(object())
    assert gate.acquire().token is None
    gate.release(a.token)
    gate.release(a.token)  # double release is a no-op
    third = gate.acquire()
    assert third.retry_after is None and third.token is not None
    assert gate.acquire().token is None
    gate.release(b.token)
    gate.release(third.token)
