from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.llm import LlmClient, OllamaClient
from app.schemas import HealthResponse, SuggestRequest, SuggestResponse
from app.suggester import MoveSuggester, NoLegalMove


def create_app(
    settings: Settings | None = None,
    llm_client: LlmClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    docs_url = "/docs" if settings.app_env == "dev" else None
    openapi_url = "/openapi.json" if settings.app_env == "dev" else None
    app = FastAPI(
        title="2048 suggestions",
        docs_url=docs_url,
        openapi_url=openapi_url,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    suggester = MoveSuggester(
        llm_client or OllamaClient(settings),
        max_attempts=settings.llm_max_attempts,
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/suggest", response_model=SuggestResponse)
    def suggest(body: SuggestRequest) -> SuggestResponse:
        try:
            return suggester.suggest(body.board, body.mode)
        except NoLegalMove:
            raise HTTPException(status_code=409, detail="no legal move") from None

    return app


app = create_app()
