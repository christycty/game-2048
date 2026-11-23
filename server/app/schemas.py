from typing import Literal

from pydantic import BaseModel, Field, model_validator

Move = Literal["up", "down", "left", "right"]
Mode = Literal["llm", "expectimax"]
Source = Literal["llm", "fallback", "expectimax"]
# Browser-reported suggest outcomes (AbortError / HTTP 499 → cancel).
# rate_limit = spend hard ceiling; model_busy = per-mode capacity gate.
ClientEventOutcome = Literal["fail", "rate_limit", "model_busy", "cancel"]
# 4 through 131072 fills all 16 cells, so a 4x4 board cannot hold a higher tile.
MAX_TILE = 1 << 17


def _is_tile(cell: int) -> bool:
    return cell == 0 or (2 <= cell <= MAX_TILE and cell & (cell - 1) == 0)


class SuggestRequest(BaseModel):
    board: list[list[int]]
    mode: Mode

    @model_validator(mode="after")
    def board_is_grid(self) -> "SuggestRequest":
        if len(self.board) != 4 or any(len(row) != 4 for row in self.board):
            raise ValueError("board must be 4x4")
        if not all(_is_tile(cell) for row in self.board for cell in row):
            raise ValueError(f"tile values must be 0 or a power of two from 2 to {MAX_TILE}")
        return self


class SuggestResponse(BaseModel):
    move: Move
    mode: Mode
    source: Source
    reason: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class ClientEventRequest(BaseModel):
    outcome: ClientEventOutcome
