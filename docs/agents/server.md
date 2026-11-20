# Server

FastAPI service that suggests the next 2048 move. The process is healthy even when Ollama is down. An LLM failure still returns a legal move from a fixed order. Expectimax runs a depth-limited search and does not call the model.

Agent/implementer detail for the API. Human architecture overview: [../architecture.md](../architecture.md). Product rules: [prd.md](prd.md).

## Run

From `server/`:

```bash
# copy server/.env.example if you want local overrides
uv sync --extra dev          # or: pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"
pytest                       # unit tests; skips e2e
pytest --e2e                 # needs a local Ollama and the configured model
ruff format --check . && ruff check .
```

Package name: `game-2048-server`. Entry: `app.main:app`. Python ≥ 3.11 (images use 3.12). See [runtime.md](runtime.md) for Compose, Docker, and env names shared with the host Ollama.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, disconnect-cancel middleware, `/health`, `/suggest` (async). |
| `app/schemas.py` | Request and response models. Tile and mode validation. |
| `app/suggester.py` | Mode dispatch, LLM retries, fallback, expectimax search; honors per-request cancel. |
| `app/expectimax.py` | Depth-limited expectimax with spawn chance nodes; checks cancel between depths. |
| `app/moves.py` | Slide/merge rules for legal moves and the fallback order. |
| `app/llm.py` | Ollama chat client, prompt, JSON parse; closes only the in-flight response on cancel. |
| `app/cancel.py` | `SuggestCancelled` — per-request stop (not process-wide). |
| `app/rate_limit.py` | Process-wide sliding-window cap for `/suggest`. |
| `app/config.py` | Env-backed settings. |
| `app/telemetry.py` | Phoenix / OpenInference tracing setup. |

## HTTP

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` | Never calls Ollama. |
| `POST` | `/suggest` | `SuggestResponse` | `409` when the board has no legal move. `422` on bad payload. `429` + `Retry-After` when that mode’s process rate limit is hit (checked before the model). `499` when the client disconnects / cancels mid-run (best-effort if already gone). |

Concurrent clients share one process (FastAPI threadpool + process-wide rate limiters). Cancel is **per request**: `DisconnectCancelMiddleware` tees ASGI receive for `/suggest` and sets that request’s `threading.Event` on `http.disconnect`. The shared Ollama `httpx.Client` stays open; cancel closes that response stream so a sibling suggest keeps running.

CORS allows `http://localhost:${CLIENT_HOST_PORT}` and `http://127.0.0.1:${CLIENT_HOST_PORT}` (default 5173), methods `GET` and `POST`. Same-origin `/suggest` through Vite or nginx does not need CORS; the allowlist remains for builds that set `VITE_API_BASE_URL` to the API origin.

In `APP_ENV=dev`, `/docs` and `/openapi.json` are open. In `prod` they return 404. Redoc is always off. Title: `2048 suggestions`.

### Request

```json
{
  "board": [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 2]],
  "mode": "llm"
}
```

`board` is exactly 4×4. Each cell is an int from `0` through `MAX_TILE` (`1 << 17`). `mode` is `llm` or `expectimax`.

### Response

```json
{
  "move": "right",
  "mode": "llm",
  "source": "llm",
  "reason": "Opens space on the left."
}
```

| Field | Values |
|---|---|
| `move` | `up`, `down`, `left`, `right` |
| `mode` | Echo of the request mode |
| `source` | `llm`, `fallback`, or `expectimax` |
| `reason` | Non-empty for `source: "llm"` (model text) and `source: "expectimax"` (score line). `null` for `fallback`. |

Expectimax reason shape (illegal directions are `N/A`):

```text
Score of each direction: Left = N/A, Right = 1053.4, Up = N/A, Down = 771.2
```

## Suggestion pipeline

`MoveSuggester.suggest`:

1. Builds the legal move set with the same slide rules as the client.
2. Picks a fallback: first direction in `FALLBACK_ORDER` (`left`, `up`, `right`, `down`) that is legal. None → `NoLegalMove` → HTTP 409.
3. **`expectimax`**: `choose_move` runs depth-limited expectimax (chance node: uniform empty cell, 2 at 90% / 4 at 10%). Returns `source: "expectimax"` with the score-line `reason`. If search returns a non-legal move, or returns nothing (budget expired or an unreachable state before any depth finished), substitutes the fallback with `source: "fallback"`. A cut mid-depth keeps the last finished depth.
4. **`llm`**: up to `LLM_MAX_ATTEMPTS` calls, stopped early when the remaining `LLM_SUGGEST_BUDGET_SECONDS` cannot cover another `LLM_ATTEMPT_TIMEOUT_SECONDS` wait.
5. Accepts a reply only when the move is legal and the reason is a non-blank string after strip.
6. Retries on illegal moves (recorded as rejected), blank reasons, and `LlmError`.
7. After exhaustion: `source: "fallback"`, `move` is the fallback, `reason` is null.

Expectimax depth: open boards (≥8 empties) search to depth 1; tighter boards to depth 2. Wall budget ~0.5s with iterative deepening (keeps the last finished depth; if none finished, falls back). `N/A` in the reason means that direction is illegal, not unscored.

## LLM (`OllamaClient`)

`POST {OLLAMA_BASE_URL}/api/chat` with `OLLAMA_MODEL`, non-streaming. The prompt lists the board, legal moves, any rejected moves, and asks for JSON `{"move":"...","reason":"..."}` only.

When `OLLAMA_STRUCTURED_OUTPUT` is true and `APP_ENV` is not `prod`, the request also sends a JSON schema that constrains `move` to the legal set. Prod always omits that schema so the model must follow the prompt text alone.

`parse_move` requires JSON with a known direction and a non-blank reason, then trims the reason to at most 50 words and 400 characters.

## Settings

Loaded from the environment and optional `server/.env` (Compose does not use that file for containers; see [runtime.md](runtime.md)).

| Setting | Default | Bounds / notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` or `prod` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host process default |
| `OLLAMA_MODEL` | `gemma4:latest` | |
| `OLLAMA_STRUCTURED_OUTPUT` | `true` | Forced off in prod |
| `LLM_MAX_ATTEMPTS` | `3` | 1–5 |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | `20` | >0, ≤20 |
| `LLM_SUGGEST_BUDGET_SECONDS` | `40` | >0, ≤40; raised to 2× attempt timeout when lower |
| `SUGGEST_RATE_LIMIT_REQUESTS` | `5` | 1–30; LLM bucket (process-wide) |
| `SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS` | `30` | 1–120; Expectimax bucket (process-wide) |
| `SUGGEST_RATE_LIMIT_WINDOW_SECONDS` | `60` | 1–3600; shared window for both modes |
| `CLIENT_HOST_PORT` | `5173` | 1–65535; CORS allowlist |
| `EXPORT_TRACES` | `true` | CI sets `false` |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Host process default |
| `PHOENIX_API_KEY` | unset | Optional |

## Tests

- `tests/test_helpers.py` asserts `isolated_settings` pins every `Settings` field and ignores hostile `SUGGEST_RATE_LIMIT_*` env.
- `tests/test_suggest.py` covers health, CORS, per-mode rate limits before the model (including the **default** 5-call LLM cap and a separate Expectimax bucket), LLM success and reason, illegal-move retry, exhausted fallback, expectimax search + score reason, illegal-search fallback, stuck-board 409, bad payload 422, Ollama HTTP failures, prod schema omission, attempt bounds, and the time budget stop.
- `tests/test_cancel.py` covers per-request cancel through suggester / expectimax / Ollama client, concurrent isolation (cancel A, B still completes), endpoint `499` mapping, disconnect middleware, and ASGI disconnect cancelling a blocking LLM while a sibling completes.
- `tests/test_expectimax.py` covers legality, spawn odds, depth/budget cutoffs, and the reason format.
- `tests/test_moves.py` covers the slide and merge rules used for legality.
- `tests/test_telemetry.py` covers span wiring for suggest.
- `tests/test_suggest_e2e.py` is marked `e2e` for real Ollama under `APP_ENV=prod`. It sizes `SUGGEST_RATE_LIMIT_REQUESTS` from its parametrized call volume, asserts `source == "llm"` with a short reason, and includes a non-e2e expectimax HTTP smoke that does not need Ollama.

## Not built yet

There is no auth or per-player quota (the suggestion cap is process-wide). The API does not persist games. Expectimax depth stays shallow for latency, not tournament strength.
