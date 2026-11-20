import json
import threading
import time
from typing import NamedTuple, Protocol

import httpx

from app import telemetry as tel
from app.cancel import SuggestCancelled
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
        cancel: threading.Event | None = None,
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
        cancel: threading.Event | None = None,
    ) -> ModelSuggestion:
        if cancel is not None and cancel.is_set():
            raise SuggestCancelled()

        prompt = _prompt(
            board,
            legal=legal,
            rejected=rejected,
            invalid_reply=invalid_reply,
        )
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if self._structured_output:
            payload["format"] = _move_schema(legal)

        # Event stamps need a unix time; the duration stays on a monotonic clock.
        started_ns = time.time_ns()
        wall_start = time.perf_counter()
        with tel.tracer().start_as_current_span("ollama chat") as span:
            tel.annotate_llm_span(span, self._model)
            # Attach the prompt now so a failed request still has it.
            tel.set_llm_messages(
                span,
                prompt=prompt,
                invocation={
                    "structured_output": self._structured_output,
                    "timeout_seconds": self._attempt_timeout,
                    "stream": False,
                },
            )
            try:
                body = self._post_chat(payload, cancel)
            except SuggestCancelled:
                tel.mark_span_error(span, SuggestCancelled())
                raise
            except httpx.TimeoutException as exc:
                error = LlmError(f"ollama request failed: {exc}")
                tel.mark_span_error(span, error)
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_TIMEOUT,
                )
                raise error from exc
            except (httpx.HTTPError, ValueError) as exc:
                error = LlmError(f"ollama request failed: {exc}")
                tel.mark_span_error(span, error)
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_ERROR,
                    error_type="request",
                )
                raise error from exc

            wall_seconds = time.perf_counter() - wall_start
            if not isinstance(body, dict):
                error = LlmError("ollama response is not an object")
                tel.mark_span_error(span, error)
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_ERROR,
                    error_type="response",
                )
                raise error
            message = body.get("message")
            if not isinstance(message, dict):
                error = LlmError("ollama response has no message")
                tel.mark_span_error(span, error)
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_ERROR,
                    error_type="response",
                )
                raise error

            raw_content = message.get("content", "")
            output_text = (
                json.dumps(raw_content) if isinstance(raw_content, dict) else str(raw_content)
            )
            finish_reason = body.get("done_reason")
            tel.set_llm_messages(
                span,
                prompt=prompt,
                output=output_text,
                finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            )
            tel.record_llm_usage(
                span,
                model=self._model,
                body=body,
                wall_seconds=wall_seconds,
                started_ns=started_ns,
            )

            # The span closes when suggest_move returns, so the status has to be set here.
            try:
                parsed = parse_move(raw_content)
            except LlmError as exc:
                tel.mark_span_error(span, exc)
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_ERROR,
                    error_type="parse",
                )
                raise
            if parsed.move not in legal:
                tel.mark_span_error(span, LlmError(f"illegal move {parsed.move}"))
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_ERROR,
                    error_type="illegal_move",
                )
            else:
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_SUCCESS,
                )
            return parsed

    def _post_chat(
        self,
        payload: dict[str, object],
        cancel: threading.Event | None,
    ) -> dict:
        """POST /api/chat; abort this call only if cancel fires (siblings keep going).

        A per-attempt client owns its connections so ``client.close()`` can interrupt
        ``post`` while it is still waiting on response headers. Injected test clients
        keep their transport via a non-closing wrapper so cancel does not break them.
        """
        if cancel is not None and cancel.is_set():
            raise SuggestCancelled()

        base_url = str(self._client.base_url)
        timeout = self._attempt_timeout
        stop_watch = threading.Event()
        watcher: threading.Thread | None = None
        if self._owns_client:
            client = httpx.Client(base_url=base_url, timeout=timeout)
        else:
            client = httpx.Client(
                base_url=base_url,
                timeout=timeout,
                transport=_NonClosingTransport(self._client._transport),
            )
        try:
            if cancel is not None:

                def _watch_cancel() -> None:
                    while not stop_watch.is_set():
                        if cancel.is_set():
                            client.close()
                            return
                        stop_watch.wait(0.05)

                watcher = threading.Thread(target=_watch_cancel, daemon=True)
                watcher.start()
            try:
                response = client.post("/api/chat", json=payload, timeout=timeout)
                if cancel is not None and cancel.is_set():
                    raise SuggestCancelled()
                response.raise_for_status()
                body = response.json()
            except SuggestCancelled:
                raise
            except (httpx.HTTPError, httpx.StreamError, ValueError, json.JSONDecodeError) as exc:
                if cancel is not None and cancel.is_set():
                    raise SuggestCancelled() from exc
                if isinstance(exc, json.JSONDecodeError):
                    raise ValueError("ollama response is not json") from exc
                raise
            finally:
                stop_watch.set()
                if watcher is not None:
                    watcher.join(timeout=1)
        finally:
            client.close()
        if not isinstance(body, dict):
            raise ValueError("ollama response is not an object")
        return body

    def close(self) -> None:
        if self._owns_client and not self._closed:
            self._closed = True
            self._client.close()


class _NonClosingTransport(httpx.BaseTransport):
    """Wrap an injected transport so attempt-client close does not tear it down."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._inner.handle_request(request)

    def close(self) -> None:
        return None


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
