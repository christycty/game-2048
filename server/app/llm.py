import json
from typing import NamedTuple, Protocol

import httpx

from app.config import Settings

DIRECTIONS = ("up", "down", "left", "right")
REASON_WORD_LIMIT = 50
# A single token has one word, so the word cap alone would not bound the payload.
REASON_CHAR_LIMIT = 400


class LlmError(Exception):
    """The model call failed or its output could not be used."""


class ModelSuggestion(NamedTuple):
    move: str
    reason: str | None = None


class LlmClient(Protocol):
    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
    ) -> ModelSuggestion: ...


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._model = settings.ollama_model
        self._structured_output = settings.ollama_structured_output
        self._attempt_timeout = settings.llm_attempt_timeout_seconds
        self._owns_client = client is None
        self._closed = False
        self._client = client or httpx.Client(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=self._attempt_timeout,
        )

    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
    ) -> ModelSuggestion:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": _prompt(
                        board,
                        legal=legal,
                        rejected=rejected,
                        invalid_reply=invalid_reply,
                    ),
                }
            ],
            "stream": False,
        }
        if self._structured_output:
            payload["format"] = _move_schema(legal)
        try:
            response = self._client.post(
                "/api/chat",
                json=payload,
                timeout=self._attempt_timeout,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmError(f"ollama request failed: {exc}") from exc

        if not isinstance(body, dict):
            raise LlmError("ollama response is not an object")
        message = body.get("message")
        if not isinstance(message, dict):
            raise LlmError("ollama response has no message")
        return parse_move(message.get("content", ""))

    def close(self) -> None:
        if self._owns_client and not self._closed:
            self._closed = True
            self._client.close()


def parse_move(content: str | dict) -> ModelSuggestion:
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
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise LlmError("model output has no reason")
    return ModelSuggestion(move, _bounded_reason(reason))


def _bounded_reason(reason: str) -> str:
    text = reason.strip()
    words = text.split()
    if len(words) > REASON_WORD_LIMIT:
        text = " ".join(words[:REASON_WORD_LIMIT])
    if len(text) > REASON_CHAR_LIMIT:
        text = text[:REASON_CHAR_LIMIT].rstrip()
    if not text:
        raise LlmError("model output has no reason")
    return text


def _move_schema(legal: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "move": {"type": "string", "enum": list(legal)},
            "reason": {"type": "string", "minLength": 1, "maxLength": REASON_CHAR_LIMIT},
        },
        "required": ["move", "reason"],
    }


def _prompt(
    board: list[list[int]],
    *,
    legal: list[str],
    rejected: list[str],
    invalid_reply: bool,
) -> str:
    rows = "\n".join(" ".join(str(cell) for cell in row) for row in board)
    lines = [
        "You are playing 2048. The board is 4x4. 0 is an empty cell. "
        "Other numbers are tile values. Choose the single best next move.",
        rows,
        f"Legal moves: {', '.join(legal)}.",
        "Choose one of those moves.",
    ]
    if rejected:
        listed = ", ".join(rejected)
        lines.append(
            f"Rejected moves: {listed}. Those do not change the board. "
            "Choose a different legal move."
        )
    if invalid_reply:
        lines.append("The previous reply could not be used. Reply with only the JSON object.")
    lines.append(
        "Reply with only a JSON object whose move is one of the legal moves. "
        'Shape: {"move":"...","reason":"..."}. '
        "reason explains the choice in at most 50 words. "
        "No markdown and no other text."
    )
    return "\n".join(lines)
