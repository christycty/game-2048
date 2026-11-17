from app.llm import LlmClient, LlmError
from app.moves import first_legal_move, legal_moves
from app.schemas import Mode, SuggestResponse


class NoLegalMove(Exception):
    """The board has no slide or merge available."""


class MoveSuggester:
    def __init__(self, llm: LlmClient, max_attempts: int = 3) -> None:
        self._llm = llm
        self._max_attempts = max_attempts

    def suggest(self, board: list[list[int]], mode: Mode) -> SuggestResponse:
        fallback = first_legal_move(board)
        if fallback is None:
            raise NoLegalMove()
        if mode == "expectimax":
            return SuggestResponse(move=fallback, mode=mode, source="expectimax-stub")

        legal = set(legal_moves(board))
        for _ in range(self._max_attempts):
            try:
                move = self._llm.suggest_move(board)
            except LlmError:
                continue
            if move in legal:
                return SuggestResponse(move=move, mode=mode, source="llm")
        return SuggestResponse(move=fallback, mode=mode, source="fallback")
