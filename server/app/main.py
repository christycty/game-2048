from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.llm import LlmClient, OllamaClient
from app.schemas import HealthResponse, SuggestRequest, SuggestResponse
from app.suggester import MoveSuggester, NoLegalMove
from app.telemetry import setup_telemetry


def create_app(
    settings: Settings | None = None,
    llm_client: LlmClient | None = None,
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

    docs_url = "/docs" if settings.app_env == "dev" else None
    openapi_url = "/openapi.json" if settings.app_env == "dev" else None
    app = FastAPI(
        title="2048 suggestions",
        docs_url=docs_url,
        openapi_url=openapi_url,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    setup_telemetry(app, settings)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        check = getattr(llm, "healthy", None)
        if check is not None and not check():
            raise HTTPException(status_code=503, detail="ollama unavailable")
        return HealthResponse(status="ok")

    @app.post("/suggest", response_model=SuggestResponse)
    def suggest(body: SuggestRequest) -> SuggestResponse:
        try:
            return suggester.suggest(body.board, body.mode)
        except NoLegalMove:
            raise HTTPException(status_code=409, detail="no legal move") from None

    return app


app = create_app()
