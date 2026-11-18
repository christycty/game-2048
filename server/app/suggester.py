import logging
import time
from collections.abc import Callable

from app.expectimax import choose_move
from app.llm import LlmClient, LlmError
from app.moves import FALLBACK_ORDER, legal_moves
from app.schemas import Mode, SuggestResponse

logger = logging.getLogger(__name__)
_Clock = Callable[[], float]


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

    def suggest(self, board: list[list[int]], mode: Mode) -> SuggestResponse:
        legal = legal_moves(board)
        fallback = next((direction for direction in FALLBACK_ORDER if direction in legal), None)
        if fallback is None:
            raise NoLegalMove()
        if mode == "expectimax":
            move = choose_move(board) or fallback
            return SuggestResponse(move=move, mode=mode, source="expectimax")

        rejected: list[str] = []
        invalid_reply = False
        failures: list[str] = []
        # Start a call only when the remaining budget covers its timeout.
        deadline = self._clock() + self._budget_seconds
        for attempt in range(1, self._max_attempts + 1):
            remaining = deadline - self._clock()
            if remaining < self._attempt_timeout_seconds:
                failures.append("time budget")
                logger.warning("llm suggestion stopped with %.1f seconds left", remaining)
                break
            try:
                suggestion = self._llm.suggest_move(
                    board,
                    legal=legal,
                    rejected=list(rejected),
                    invalid_reply=invalid_reply,
                )
            except LlmError as exc:
                invalid_reply = True
                failures.append(str(exc))
                logger.warning("llm attempt %s failed: %s", attempt, exc)
                continue

            reason = suggestion.reason
            if suggestion.move in legal and isinstance(reason, str) and reason.strip():
                return SuggestResponse(
                    move=suggestion.move,
                    mode=mode,
                    source="llm",
                    reason=reason.strip(),
                )

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
        return SuggestResponse(move=fallback, mode=mode, source="fallback")
