from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanProcessor

from app.config import Settings
from app.llm import LlmClient, OllamaClient
from app.schemas import HealthResponse, SuggestRequest, SuggestResponse
from app.suggester import MoveSuggester, NoLegalMove
from app.telemetry import (
    mark_chain_io,
    mark_span_error,
    set_json_io,
    setup_telemetry,
    shutdown_telemetry,
)


def create_app(
    settings: Settings | None = None,
    llm_client: LlmClient | None = None,
    span_processor: SpanProcessor | None = None,
) -> FastAPI:
    settings = settings or Settings()
    owns_llm = llm_client is None
    llm = llm_client or OllamaClient(settings)
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
    # localhost and 127.0.0.1 are different browser origins. The prod client
    # is published on 5173 so either way of opening the page can call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    setup_telemetry(app, settings, span_processor)

    # The process is up even when Ollama is not. Expectimax never calls the
    # model, and an llm failure still returns a legal move.
    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/suggest", response_model=SuggestResponse)
    def suggest(body: SuggestRequest) -> SuggestResponse:
        span = trace.get_current_span()
        set_json_io(span, input_payload={"board": body.board, "mode": body.mode})
        try:
            result = suggester.suggest(body.board, body.mode)
        except NoLegalMove as exc:
            mark_span_error(span, exc)
            set_json_io(span, output_payload={"detail": "no legal move"})
            raise HTTPException(status_code=409, detail="no legal move") from None
        mark_chain_io(
            span,
            input_payload={"board": body.board, "mode": body.mode},
            output_payload=result.model_dump(),
        )
        return result

    return app


app = create_app()
