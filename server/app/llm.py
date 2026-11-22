import asyncio
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
        # Production opens a fresh client per attempt (cancel closes that one only).
        # Injected clients supply base_url / transport for tests; no idle pool either way.
        self._injected = client
        self._base_url = (
            str(client.base_url).rstrip("/")
            if client is not None
            else settings.ollama_base_url.rstrip("/")
        )
        self._closed = False

    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
        cancel: threading.Event | None = None,
    ) -> ModelSuggestion:
        # Cancel already set is handled inside the span via _post_chat so the
        # attempt still records gen_ai cancelled (not a silent pre-span raise).
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
        # Manual status: cancel must not look like a model ERROR in Phoenix.
        with tel.tracer().start_as_current_span(
            "ollama chat",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
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
                tel.record_llm_request_count(
                    self._model,
                    outcome=tel.REQUEST_OUTCOME_CANCELLED,
                )
                tel.mark_span_cancelled(span)
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

        Production uses ``httpx.AsyncClient`` + ``task.cancel()`` so a mid-flight
        cancel does not close sockets from another thread. Injected test clients keep
        the sync MockTransport path (pre/post cancel checks; no real network wait).
        """
        if cancel is not None and cancel.is_set():
            raise SuggestCancelled()

        if self._injected is not None:
            return self._post_chat_sync(payload, cancel)
        return self._post_chat_async(payload, cancel)

    def _post_chat_sync(
        self,
        payload: dict[str, object],
        cancel: threading.Event | None,
    ) -> dict:
        assert self._injected is not None
        timeout = self._attempt_timeout
        client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=_NonClosingTransport(self._injected._transport),
        )
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
            client.close()
        if not isinstance(body, dict):
            raise ValueError("ollama response is not an object")
        return body

    def _post_chat_async(
        self,
        payload: dict[str, object],
        cancel: threading.Event | None,
    ) -> dict:
        """POST /api/chat on a dedicated async client with cancel polling.

        Sync-vs-async entry (exactly one POST; never fall through both branches)::

            _post_chat_async
              ├─ no running loop  → asyncio.run(_run)     # FastAPI to_thread
              └─ loop already on  → fresh thread + run     # tests / nested callers
                   (avoid awaiting here: would block the outer loop)

            _run: AsyncClient → create_task(POST) → _wait_chat_post_or_cancel
        """
        timeout = self._attempt_timeout

        async def _run() -> dict:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
                task = asyncio.create_task(client.post("/api/chat", json=payload))
                return await _wait_chat_post_or_cancel(task, cancel)

        # Prefer asyncio.run when this thread has no loop (normal FastAPI to_thread).
        # A broad except RuntimeError would re-enter _run after a mid-flight failure
        # and could POST to Ollama twice — only branch on "already running a loop".
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_run())

        outcome: dict[str, object] = {}

        def _in_fresh_thread() -> None:
            try:
                outcome["body"] = asyncio.run(_run())
            except BaseException as exc:  # noqa: BLE001 — re-raise on the caller thread
                outcome["error"] = exc

        thread = threading.Thread(target=_in_fresh_thread)
        thread.start()
        thread.join()
        error = outcome.get("error")
        if error is not None:
            raise error
        body = outcome.get("body")
        if not isinstance(body, dict):
            raise LlmError("ollama response is not an object")
        return body

    def close(self) -> None:
        # No long-lived pool; attempts own their clients. Keep the hook for lifespan.
        self._closed = True


async def _wait_chat_post_or_cancel(
    task: asyncio.Task,
    cancel: threading.Event | None,
) -> dict:
    """Poll cancel while an httpx POST task runs; map cancel to SuggestCancelled."""
    while True:
        if cancel is not None and cancel.is_set():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, httpx.HTTPError, httpx.StreamError):
                pass
            raise SuggestCancelled()
        done, _ = await asyncio.wait({task}, timeout=0.05)
        if not done:
            continue
        try:
            response = task.result()
        except asyncio.CancelledError as exc:
            raise SuggestCancelled() from exc
        except (httpx.HTTPError, httpx.StreamError, ValueError) as exc:
            if cancel is not None and cancel.is_set():
                raise SuggestCancelled() from exc
            raise
        if cancel is not None and cancel.is_set():
            raise SuggestCancelled()
        response.raise_for_status()
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("ollama response is not json") from exc
        if not isinstance(body, dict):
            raise ValueError("ollama response is not an object")
        return body


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
        "Other numbers are tile values. The goal is to reach a 2048 tile. "
        "Choose the single best next move.",
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
