from typing import Literal

from pydantic import BaseModel, Field, model_validator

Move = Literal["up", "down", "left", "right"]
Mode = Literal["llm", "expectimax"]
Source = Literal["llm", "fallback", "expectimax-stub"]


class SuggestRequest(BaseModel):
    board: list[list[int]]
    mode: Mode

    @model_validator(mode="after")
    def board_is_grid(self) -> "SuggestRequest":
        if len(self.board) != 4 or any(len(row) != 4 for row in self.board):
            raise ValueError("board must be 4x4")
        if any(cell < 0 for row in self.board for cell in row):
            raise ValueError("tile values must be non-negative")
        return self


class SuggestResponse(BaseModel):
    move: Move
    mode: Mode
    source: Source
    reason: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
