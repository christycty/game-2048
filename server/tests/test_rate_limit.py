"""Unit tests for sliding-window and in-flight capacity gates (no HTTP)."""

import pytest

from app.rate_limit import InFlightGate


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
