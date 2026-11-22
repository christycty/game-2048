import asyncio
import contextlib
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanProcessor
from starlette.types import ASGIApp, Receive, Scope, Send

from app.cancel import SuggestCancelled
from app.config import Settings
from app.llm import LlmClient, OllamaClient
from app.rate_limit import LlmInFlightGate, SuggestRateLimiter
from app.schemas import ClientEventRequest, HealthResponse, SuggestRequest, SuggestResponse
from app.suggester import MoveSuggester, NoLegalMove
from app.telemetry import (
    mark_chain_io,
    mark_span_error,
    record_client_suggest_outcome,
    set_json_io,
    setup_telemetry,
    shutdown_telemetry,
)


class DisconnectCancelMiddleware:
    """Tee ASGI receive so a client disconnect sets a per-request cancel Event.

    ``request.is_disconnected()`` only peeks; a lone ``request.receive()`` after
    the body is read can still miss disconnects under instrumentation. One pump
    task owns the raw receive channel, forwards messages to the app, and sets
    ``request.state.suggest_cancel`` on ``http.disconnect``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/suggest":
            await self.app(scope, receive, send)
            return

        cancel = threading.Event()
        scope.setdefault("state", {})
        scope["state"]["suggest_cancel"] = cancel
        bridge: asyncio.Queue[dict] = asyncio.Queue()

        async def pump() -> None:
            try:
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        cancel.set()
                    await bridge.put(message)
                    if message.get("type") == "http.disconnect":
                        return
            except Exception:
                cancel.set()
                await bridge.put({"type": "http.disconnect"})

        async def bridged_receive() -> dict:
            return await bridge.get()

        pump_task = asyncio.create_task(pump())
        try:
            await self.app(scope, bridged_receive, send)
        finally:
            cancel.set()
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task


def create_app(
    settings: Settings | None = None,
    llm_client: LlmClient | None = None,
    span_processor: SpanProcessor | None = None,
    rate_limiters: dict[str, SuggestRateLimiter] | None = None,
    llm_in_flight: LlmInFlightGate | None = None,
) -> FastAPI:
    settings = settings or Settings()
    owns_llm = llm_client is None
    llm = llm_client or OllamaClient(settings)
    window = settings.suggest_rate_limit_window_seconds
    limiters = rate_limiters or {
        "llm": SuggestRateLimiter(settings.suggest_rate_limit_requests, window),
        "expectimax": SuggestRateLimiter(
            settings.suggest_rate_limit_expectimax_requests,
            window,
        ),
    }
    in_flight = llm_in_flight or LlmInFlightGate(settings.llm_max_in_flight)
    suggester = MoveSuggester(
        llm,
        max_attempts=settings.llm_max_attempts,
        budget_seconds=settings.llm_suggest_budget_seconds,
        attempt_timeout_seconds=settings.llm_attempt_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owns_llm:
            llm.close()
        shutdown_telemetry(_app)

    docs_url = "/docs" if settings.app_env == "dev" else None
    openapi_url = "/openapi.json" if settings.app_env == "dev" else None
    app = FastAPI(
        title="2048 suggestions",
        docs_url=docs_url,
        openapi_url=openapi_url,
        redoc_url=None,
        lifespan=lifespan,
    )
    # The page calls same-origin /suggest. This list is for a build that sets
    # VITE_API_BASE_URL to the API origin. localhost and 127.0.0.1 differ.
    # CLIENT_HOST_PORT moves with the worktree when 5173 is taken.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    setup_telemetry(app, settings, span_processor)
    # Outermost: last added runs first so the pump sees uvicorn's disconnect.
    app.add_middleware(DisconnectCancelMiddleware)

    # The process is up even when Ollama is not. Expectimax never calls the
    # model, and an llm failure still returns a legal move. /metrics is
    # registered in setup_telemetry for Prometheus-compatible scrapes.
    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    # Thin client beacons: fail / rate_limit counts for Grafana. Not traced
    # (see _EXCLUDED_URLS). Cancel outcome waits on AbortSignal.
    @app.post("/client-events", status_code=204, include_in_schema=False)
    def client_events(body: ClientEventRequest) -> None:
        record_client_suggest_outcome(body.outcome)

    @app.post("/suggest", response_model=SuggestResponse)
    async def suggest(request: Request, body: SuggestRequest) -> SuggestResponse:
        # Layer 1: per-mode sliding-window hard ceiling (spend / runaway safety).
        gate = limiters[body.mode].allow()
        if gate.retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="too many suggestions",
                headers={"Retry-After": str(gate.retry_after)},
            )
        # Layer 2 (LLM only): in-flight capacity before calling Ollama.
        slot: object | None = None
        if body.mode == "llm":
            capacity = in_flight.acquire()
            if capacity.retry_after is not None:
                # Rejected before Ollama — do not burn the hard-ceiling hit.
                if gate.token is not None:
                    limiters[body.mode].release(gate.token)
                raise HTTPException(
                    status_code=429,
                    detail="too many suggestions",
                    headers={"Retry-After": str(capacity.retry_after)},
                )
            slot = capacity.token
        # try starts immediately after acquire so a pre-suggester failure cannot leak the slot
        # (default LLM_MAX_IN_FLIGHT=1 would sticky-429 until restart).
        try:
            span = trace.get_current_span()
            set_json_io(span, input_payload={"board": body.board, "mode": body.mode})
            # Middleware installs a per-request Event; fall back for non-HTTP callers.
            cancel = getattr(request.state, "suggest_cancel", None) or threading.Event()
            result = await asyncio.to_thread(suggester.suggest, body.board, body.mode, cancel)
        except SuggestCancelled as exc:
            # Refund this request's hit only (token), so concurrent siblings keep theirs.
            if gate.token is not None:
                limiters[body.mode].release(gate.token)
            mark_span_error(span, exc)
            set_json_io(span, output_payload={"detail": "cancelled"})
            # 499 = client closed request (nginx convention). Best-effort if already gone.
            raise HTTPException(status_code=499, detail="client cancelled") from None
        except NoLegalMove as exc:
            mark_span_error(span, exc)
            set_json_io(span, output_payload={"detail": "no legal move"})
            raise HTTPException(status_code=409, detail="no legal move") from None
        finally:
            if slot is not None:
                in_flight.release(slot)
        mark_chain_io(
            span,
            input_payload={"board": body.board, "mode": body.mode},
            output_payload=result.model_dump(),
        )
        return result

    return app


app = create_app()
