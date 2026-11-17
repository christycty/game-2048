import json
from typing import Protocol

import httpx

from app.config import Settings

DIRECTIONS = ("up", "down", "left", "right")

MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "move": {"type": "string", "enum": list(DIRECTIONS)},
    },
    "required": ["move"],
}


class LlmError(Exception):
    """The model call failed or its output could not be used."""


class LlmClient(Protocol):
    def suggest_move(self, board: list[list[int]]) -> str: ...


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._model = settings.ollama_model
        self._client = client or httpx.Client(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=30.0,
        )

    def suggest_move(self, board: list[list[int]]) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": _prompt(board)}],
            "stream": False,
            "format": MOVE_SCHEMA,
        }
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmError("ollama request failed") from exc

        if not isinstance(body, dict):
            raise LlmError("ollama response is not an object")
        message = body.get("message")
        if not isinstance(message, dict):
            raise LlmError("ollama response has no message")
        return parse_move(message.get("content", ""))


def parse_move(content: str | dict) -> str:
    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError("model output is not json") from exc
    else:
        raise LlmError("model output is not json")
    if not isinstance(payload, dict):
        raise LlmError("model output is not an object")
    move = payload.get("move")
    if move not in DIRECTIONS:
        raise LlmError("model output has no legal direction name")
    return move


def _prompt(board: list[list[int]]) -> str:
    rows = "\n".join(" ".join(str(cell) for cell in row) for row in board)
    return (
        "You are playing 2048. The board is 4x4. 0 is an empty cell. "
        "Other numbers are tile values. Choose the single best next move.\n"
        f"{rows}"
    )
