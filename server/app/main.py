from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.llm import LlmClient, OllamaClient
from app.rate_limit import SuggestRateLimiter
from app.schemas import HealthResponse, SuggestRequest, SuggestResponse
from app.suggester import MoveSuggester, NoLegalMove


def create_app(
    settings: Settings | None = None,
    llm_client: LlmClient | None = None,
    rate_limiter: SuggestRateLimiter | None = None,
) -> FastAPI:
    settings = settings or Settings()
    owns_llm = llm_client is None
    llm = llm_client or OllamaClient(settings)
    limiter = rate_limiter or SuggestRateLimiter(
        settings.suggest_rate_limit_requests,
        settings.suggest_rate_limit_window_seconds,
    )
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # The process is up even when Ollama is not. Expectimax never calls the
    # model, and an llm failure still returns a legal move.
    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/suggest", response_model=SuggestResponse)
    def suggest(body: SuggestRequest) -> SuggestResponse:
        retry_after = limiter.allow()
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="too many suggestions",
                headers={"Retry-After": str(retry_after)},
            )
        try:
            return suggester.suggest(body.board, body.mode)
        except NoLegalMove:
            raise HTTPException(status_code=409, detail="no legal move") from None

    return app


app = create_app()
