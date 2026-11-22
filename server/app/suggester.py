import logging
import threading
import time
from collections.abc import Callable

from app import telemetry as tel
from app.cancel import SuggestCancelled
from app.expectimax import choose_move
from app.llm import LlmClient, LlmError
from app.moves import FALLBACK_ORDER, legal_moves
from app.schemas import Mode, SuggestResponse

logger = logging.getLogger(__name__)
_Clock = Callable[[], float]


def _record_result(span, result: SuggestResponse, failures: list[str]) -> SuggestResponse:
    payload = result.model_dump()
    if failures:
        payload = {**payload, "failures": failures}
    tel.set_json_io(span, output_payload=payload)
    tel.record_suggest_source(result.source)
    return result


class NoLegalMove(Exception):
    """The board has no slide or merge available."""


class MoveSuggester:
    def __init__(
        self,
        llm: LlmClient,
        max_attempts: int = 3,
        budget_seconds: float = 40,
        attempt_timeout_seconds: float = 20,
        clock: _Clock | None = None,
    ) -> None:
        self._llm = llm
        self._max_attempts = max_attempts
        self._budget_seconds = budget_seconds
        self._attempt_timeout_seconds = attempt_timeout_seconds
        self._clock = clock or time.monotonic

    def suggest(
        self,
        board: list[list[int]],
        mode: Mode,
        cancel: threading.Event | None = None,
    ) -> SuggestResponse:
        def raise_if_cancelled() -> None:
            if cancel is not None and cancel.is_set():
                raise SuggestCancelled()

        raise_if_cancelled()
        legal = legal_moves(board)
        fallback = next((direction for direction in FALLBACK_ORDER if direction in legal), None)
        if fallback is None:
            raise NoLegalMove()

        with tel.chain_span(
            "suggest",
            input_payload={"mode": mode, "board": board, "legal": legal},
        ) as suggest_span:
            if mode == "expectimax":
                choice = choose_move(board, cancel=cancel)
                if choice is not None and choice.move in legal:
                    result = SuggestResponse(
                        move=choice.move,
                        mode=mode,
                        source="expectimax",
                        reason=choice.reason,
                    )
                    return _record_result(suggest_span, result, [])
                # None = unscored/broken search; otherwise a move outside legal_moves.
                detail = "no scored move" if choice is None else f"illegal move {choice.move}"
                logger.warning("expectimax %s; falling back to %s", detail, fallback)
                result = SuggestResponse(move=fallback, mode=mode, source="fallback")
                return _record_result(suggest_span, result, [detail])

            rejected: list[str] = []
            invalid_reply = False
            failures: list[str] = []
            # Start a call only when the remaining budget covers its timeout.
            deadline = self._clock() + self._budget_seconds
            for attempt in range(1, self._max_attempts + 1):
                raise_if_cancelled()
                remaining = deadline - self._clock()
                if remaining < self._attempt_timeout_seconds:
                    failures.append("time budget")
                    logger.warning("llm suggestion stopped with %.1f seconds left", remaining)
                    break

                # Each try is a sibling LLM span under suggest; no attempt wrapper.
                try:
                    suggestion = self._llm.suggest_move(
                        board,
                        legal=legal,
                        rejected=list(rejected),
                        invalid_reply=invalid_reply,
                        cancel=cancel,
                    )
                except SuggestCancelled:
                    raise
                except LlmError as exc:
                    invalid_reply = True
                    failures.append(str(exc))
                    logger.warning("llm attempt %s failed: %s", attempt, exc)
                    continue

                reason = suggestion.reason
                if suggestion.move in legal and isinstance(reason, str) and reason.strip():
                    result = SuggestResponse(
                        move=suggestion.move,
                        mode=mode,
                        source="llm",
                        reason=reason.strip(),
                    )
                    return _record_result(suggest_span, result, failures)

                # The client span is already closed; this only builds the retry text.
                if suggestion.move not in legal:
                    detail = f"illegal move {suggestion.move}"
                    if suggestion.move not in rejected:
                        rejected.append(suggestion.move)
                    invalid_reply = False
                else:
                    detail = "blank reason"
                    invalid_reply = True
                failures.append(detail)
                logger.warning("llm attempt %s rejected: %s", attempt, detail)

            logger.warning("llm suggestion fell back to %s: %s", fallback, "; ".join(failures))
            result = SuggestResponse(move=fallback, mode=mode, source="fallback")
            return _record_result(suggest_span, result, failures)
