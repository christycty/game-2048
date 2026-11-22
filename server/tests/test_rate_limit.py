"""Unit tests for sliding-window and LLM in-flight gates (no HTTP)."""

from app.rate_limit import LlmInFlightGate


def test_llm_in_flight_admits_up_to_max() -> None:
    gate = LlmInFlightGate(2)
    first = gate.acquire()
    second = gate.acquire()
    assert first.retry_after is None and first.token is not None
    assert second.retry_after is None and second.token is not None
    blocked = gate.acquire()
    assert blocked.token is None
    assert blocked.retry_after == 1


def test_llm_in_flight_release_only_frees_matching_token() -> None:
    """Under max>1, unknown/double release must not steal a sibling's slot."""
    gate = LlmInFlightGate(2)
    a = gate.acquire()
    b = gate.acquire()
    assert a.token is not None and b.token is not None

    gate.release(object())  # unknown — no-op
    still_full = gate.acquire()
    assert still_full.token is None

    gate.release(a.token)
    gate.release(a.token)  # double — no-op
    # One slot free (A's); B still holds the other.
    again = gate.acquire()
    assert again.retry_after is None and again.token is not None
    assert gate.acquire().token is None

    gate.release(b.token)
    gate.release(again.token)
    assert gate.acquire().retry_after is None
