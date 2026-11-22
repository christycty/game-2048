from typing import Literal

from pydantic import BaseModel, Field, model_validator

Move = Literal["up", "down", "left", "right"]
Mode = Literal["llm", "expectimax"]
Source = Literal["llm", "fallback", "expectimax"]
# Browser-reported suggest outcomes (cancel waits on AbortSignal).
ClientEventOutcome = Literal["fail", "rate_limit"]
# 4 through 131072 fills all 16 cells, so a 4x4 board cannot hold a higher tile.
MAX_TILE = 1 << 17


class SuggestRequest(BaseModel):
    board: list[list[int]]
    mode: Mode

    @model_validator(mode="after")
    def board_is_grid(self) -> "SuggestRequest":
        if len(self.board) != 4 or any(len(row) != 4 for row in self.board):
            raise ValueError("board must be 4x4")
        if any(cell < 0 or cell > MAX_TILE for row in self.board for cell in row):
            raise ValueError(f"tile values must be between 0 and {MAX_TILE}")
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
