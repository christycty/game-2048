# Server

FastAPI service that suggests the next 2048 move. The process is healthy even when Ollama is down. On LLM exhaustion or an expectimax search miss the API still returns HTTP 200 with `source: "fallback"` and a legal move from a fixed order; the client treats fallback as an unusable suggestion (no **Play**—same as other failures). Expectimax runs a depth-limited search and does not call the model.

Agent/implementer detail for the API. Human architecture overview: [../architecture.md](../architecture.md). Product rules: [prd.md](prd.md).

## Run

From `server/`:

```bash
# copy server/.env.example if you want local overrides
uv sync --extra dev          # or: pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"
pytest                       # unit/API/concurrency; skips e2e + load
pytest --e2e                 # needs a local Ollama and the configured model
pytest --load -m load        # opt-in FakeLLM soak (not required PR CI)
ruff format --check . && ruff check .
```

Package name: `game-2048-server`. Entry: `app.main:app`. Python ≥ 3.11 (images use 3.12). See [runtime.md](runtime.md) for Compose, Docker, and env names shared with the host Ollama.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, hard-ceiling + per-mode in-flight gates (LLM + Expectimax), disconnect-cancel middleware (pump diagram in module docstring), `/health`, `/suggest` (async; spend refund via `_release_spend_token`), `/client-events`, `/metrics`. |
| `app/schemas.py` | Request and response models. Tile and mode validation. |
| `app/suggester.py` | Mode dispatch, LLM retries, fallback, expectimax search; honors per-request cancel. |
| `app/expectimax.py` | Depth-limited expectimax with spawn chance nodes; checks cancel between depths and inside chance/max nodes. |
| `app/moves.py` | Slide/merge rules; shared `DIRECTIONS` / `FALLBACK_ORDER` / `legal_moves` / `first_legal_move` (suggester + expectimax + LLM parse). |
| `app/llm.py` | Ollama chat client, prompt, JSON parse; per-attempt `AsyncClient` with `_wait_chat_post_or_cancel` poll + `task.cancel()` on disconnect (sync MockTransport path for tests). Nested-loop callers use a fresh thread so `_run` is not POSTed twice. |
| `app/cancel.py` | `SuggestCancelled` — per-request stop (not process-wide). |
| `app/rate_limit.py` | Per-mode sliding-window hard ceiling (`SuggestRateLimiter.release` refunds after cancel) + `InFlightGate` token-tracked capacity gates (separate LLM and Expectimax instances). Shared detail/header constants: `DETAIL_SPEND_CAP` / `DETAIL_MODEL_BUSY`, `X-Suggest-Limit`. Same limiter type gates `/client-events` (separate settings). |
| `app/config.py` | Env-backed settings. |
| `app/telemetry.py` | Phoenix OTLP traces + Prometheus `/metrics` (GenAI histograms + request_count). |

## HTTP

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` | Never calls Ollama. |
| `GET` | `/metrics` | Prometheus text | Always on. GenAI + FastAPI HTTP series; inventory in [telemetry.md](telemetry.md). Not traced. |
| `POST` | `/suggest` | `SuggestResponse` | Handler order: Pydantic `422` (before either gate; does not consume caps) → that mode’s hard-ceiling sliding window `429` + `Retry-After` + `detail: "too many suggestions"` + `X-Suggest-Limit: spend` → that mode’s in-flight capacity acquire `429` + `Retry-After: 1` + `detail: "model busy"` + `X-Suggest-Limit: capacity` (refunds the hard-ceiling hit if capacity is full; LLM and Expectimax gates are independent) → suggester → `409` when no legal move → `200` with `SuggestResponse`. Both reject paths increment `suggest_limit_reject_total{reason}`. Accepts W3C `traceparent` (FastAPI OTel extract). `499` when the client disconnects / cancels mid-run (best-effort if already gone); that request’s hard-ceiling token is released and its in-flight slot is freed in `finally`. |
| `POST` | `/client-events` | empty `204` | Browser beacon `{ "outcome": "fail" \| "rate_limit" \| "model_busy" \| "cancel" }` → `client_suggest_outcome_total`. Handler order: Pydantic `422` (does not consume the beacon cap) → process-wide beacon rate limit `429` + `Retry-After` (no scrape bump) → `204`. Not traced. |

Concurrent clients share one process (FastAPI threadpool + process-wide rate limiters + per-mode in-flight gates). Cancel is **per request**: `DisconnectCancelMiddleware` tees ASGI receive for `/suggest` and sets that request’s `threading.Event` on `http.disconnect`. Each Ollama attempt uses its own `httpx.AsyncClient`; cancel cancels that attempt’s asyncio task so a blocked `post` unblocks without touching sibling suggests.

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
2. Picks a fallback via `first_legal_move` (first `FALLBACK_ORDER` direction that is legal: `left`, `up`, `right`, `down`). None → `NoLegalMove` → HTTP 409.
3. **`expectimax`**: `choose_move` runs depth-limited expectimax (chance node: uniform empty cell, 2 at 90% / 4 at 10%; boards with a tile ≥ 2048 score as a hard win, matching the client). Returns `source: "expectimax"` with the score-line `reason`. If search returns a non-legal move, or returns nothing (budget expired or an unreachable state before any depth finished), substitutes the fallback with `source: "fallback"`. A cut mid-depth keeps the last finished depth.
4. **`llm`**: up to `LLM_MAX_ATTEMPTS` calls, stopped early when the remaining `LLM_SUGGEST_BUDGET_SECONDS` cannot cover another `LLM_ATTEMPT_TIMEOUT_SECONDS` wait.
5. Accepts a reply only when the move is legal and the reason is a non-blank string after strip.
6. Retries on illegal moves (recorded as rejected), blank reasons, and `LlmError`.
7. After exhaustion: `source: "fallback"`, `move` is the fallback, `reason` is null.

Expectimax depth: open boards (≥8 empties) search to depth 1; tighter boards to depth 2. Wall budget ~0.5s with iterative deepening (keeps the last finished depth; if none finished, falls back). `N/A` in the reason means that direction is illegal, not unscored.

## LLM (`OllamaClient`)

`POST {OLLAMA_BASE_URL}/api/chat` with `OLLAMA_MODEL`, non-streaming. The prompt lists the board, legal moves, any rejected moves, and asks for JSON `{"move":"...","reason":"..."}` only.

Each attempt uses its own `httpx` client. Async path: `_post_chat_async` → create_task(POST) → `_wait_chat_post_or_cancel` (50ms poll; cancel → `task.cancel()` → `SuggestCancelled`). Entry is exactly one POST: no running loop → `asyncio.run`; loop already on → fresh thread + `asyncio.run` (never await on the outer loop). Sync MockTransport path stays for unit tests.

`OLLAMA_STRUCTURED_OUTPUT` is off by default. When opted in and `APP_ENV` is not `prod`, the request also sends a JSON schema that constrains `move` to the legal set. Prod always omits that schema so the model must follow the prompt text alone.

`parse_move` requires JSON with a known direction and a non-blank reason, then trims the reason to at most 50 words and 400 characters.

## Settings

Loaded from the environment and optional `server/.env` (Compose does not use that file for containers; see [runtime.md](runtime.md)).

| Setting | Default | Bounds / notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` or `prod` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host process default |
| `OLLAMA_MODEL` | `gemma4:latest` | |
| `OLLAMA_STRUCTURED_OUTPUT` | `false` | Opt in; forced off in prod |
| `LLM_MAX_ATTEMPTS` | `3` | 1–5 |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | `20` | >0, ≤20 |
| `LLM_SUGGEST_BUDGET_SECONDS` | `40` | >0, ≤40; raised to 2× attempt timeout when lower |
| `SUGGEST_RATE_LIMIT_REQUESTS` | `60` | 1–120; LLM hard ceiling (spend safety net) |
| `SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS` | `360` | 1–600; Expectimax spend cap (process-wide; ~4 Auto Play tabs @ upper-bound settle+gap cadence) |
| `SUGGEST_RATE_LIMIT_WINDOW_SECONDS` | `60` | 1–3600; shared window for both modes |
| `LLM_MAX_IN_FLIGHT` | `1` | 1–8; concurrent LLM suggests admitted to Ollama |
| `EXPECTIMAX_MAX_IN_FLIGHT` | `4` | 1–8; concurrent Expectimax searches (CPU; matches ~4 demo tabs) |
| `CLIENT_EVENTS_RATE_LIMIT_REQUESTS` | `60` | 1–600; process-wide `/client-events` integrity cap |
| `CLIENT_EVENTS_RATE_LIMIT_WINDOW_SECONDS` | `60` | 1–3600; beacon window (separate from suggest) |
| `CLIENT_HOST_PORT` | `5173` | 1–65535; CORS allowlist |
| `EXPORT_TRACES` | `true` | Gates **OTLP export** only (instrumentation still loads when `false`). Host uvicorn / one-off image runs honor this env; CI pytest and smoke `docker run` set `false`. Compose `dev`/`prod` hardcode `true` (see [runtime.md](runtime.md)). Metrics / `GET /metrics` stay on regardless. |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Host process default; exporter posts to `{endpoint}/v1/traces` (or a full traces URL). Compose uses `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`. |
| `PHOENIX_API_KEY` | unset | Optional bearer; sent only for HTTPS or local/`host.docker.internal` HTTP |

## Observability

Phoenix = forensics (spans, prompts, retries, TTFT events). Grafana = ops aggregates from Prometheus scrapes of `GET /metrics`. Prometheus stores the time series; Grafana only queries them. Full inventory (every span, event, series, label, and Phoenix vs Grafana ownership): [telemetry.md](telemetry.md). Compose scrape UI: [runtime.md](runtime.md).

Typical LLM tree: FastAPI `POST /suggest` → `suggest` chain → sibling `ollama chat` spans per attempt. Expectimax opens `suggest` without LLM children. Stuck board (`409`) is a single HTTP span (no nested `suggest`). Auto HTTP spans skip `/health`, `/metrics`, `/client-events`, `/docs`, `/openapi.json`, `/redoc`. Retry/fallback detail may appear as span-only `failures` output (not in the API body).

## Tests

Shared Fake/Blocking LLM doubles and `asgi_suggest` live in `tests/helpers.py` (used by suggest, cancel, contract, and load).

- `tests/test_helpers.py` asserts `isolated_settings` pins every `Settings` field and ignores hostile `SUGGEST_RATE_LIMIT_*` / `LLM_MAX_IN_FLIGHT` / `EXPECTIMAX_MAX_IN_FLIGHT` / `CLIENT_EVENTS_RATE_LIMIT_*` env.
- `tests/test_rate_limit.py` covers `InFlightGate` admit/block, token-safe release under `max_in_flight > 1`, and invalid max.
- `tests/test_suggest.py` covers health, CORS, per-mode hard ceilings before the suggester (including the **default** 60-call LLM hard ceiling and a separate Expectimax bucket), LLM and Expectimax in-flight capacity (LLM: second call `model busy` 429 while first holds; two slots then third blocked; Expectimax: fifth of four blocked; capacity reject does not burn either hard ceiling; modes do not share slots; 422/409 and pre-suggester failure do not leak slots for either mode; held-slot overlap gets fail-fast 429 then frees for LLM and Expectimax), LLM success and reason, illegal-move retry, exhausted fallback, expectimax search + score reason, illegal-search fallback, stuck-board 409, bad payload 422, Ollama HTTP failures, prod schema omission, attempt bounds, and the time budget stop.
- `tests/test_suggest_http_contract.py` covers health, `/metrics`, `422` (no rate-limit spend), stuck-board `409`, spend `429` (`too many suggestions` + `X-Suggest-Limit: spend`) vs capacity `429` (`model busy` + `X-Suggest-Limit: capacity`) for **LLM and Expectimax**, spend `Retry-After` collapse to `1` near window end, expectimax search, unreachable-Ollama `fallback`, `/client-events` beacons (`fail` / `rate_limit` / `model_busy` / `cancel`) → scrape series, beacon `422` (no integrity-cap spend), beacon-cap exhaust → `429` with counter unchanged, and independence from the suggest bucket (default suite / CI). Cancel `499` lives in `test_cancel.py`.
- `tests/test_cancel.py` covers per-request cancel through suggester / expectimax (pre-set and mid-search via `_check`) / Ollama client (pre-set, mid-flight hanging POST with `task.cancel`, and single-POST when the caller already has a running loop), concurrent isolation (cancel A, B still completes; LLM isolation raises `LLM_MAX_IN_FLIGHT`), endpoint `499` mapping, disconnect middleware, concurrent ASGI disconnect cancelling A while B completes (LLM and Expectimax) **and mid-flight occupancy for both modes** (after A’s 499 with `max_in_flight=2`, a third `/suggest` admits while B holds and a fourth is capacity-429), rate-limit token refund and in-flight slot release after cancel (LLM and Expectimax), and concurrent release not popping a sibling’s hit.
- `tests/test_load_suggest.py` is marked `load` (opt-in soak): **sustained** capacity hold while workers hammer `429`, then drain + completes at `LLM_MAX_IN_FLIGHT` 1 then 2; mixed hard-ceiling + capacity `429` on **one** app with a frozen clock; ASGI disconnect-under-capacity waves with a mid-hold capacity probe; asserts accounting and no slot leak after drain.
- `tests/test_load_expectimax.py` is marked `load`: four Auto Play–cadence workers (cycle read from `client/src/game/game.js`) for **one full 60s window** against Expectimax; default spend (360) + `EXPECTIMAX_MAX_IN_FLIGHT=4` yields **0** spend/capacity `429` and `ok` above the interim single-tab-ish 120 bar; undersized spend trips spend `429`; undersized `max_in_flight=1` trips capacity `429` (workers back off `Retry-After` on capacity, settle+gap otherwise).
- `tests/test_expectimax.py` covers legality, spawn odds, win-at-2048 preference, depth/budget cutoffs, and the reason format.
- `tests/test_moves.py` covers the slide and merge rules used for legality.
- `tests/test_telemetry.py` covers Phoenix URL/header rules, per-app exporters, excluded `/health` / `/metrics` / `/client-events`, client `traceparent` continuation, client beacon counters (incl. `cancel` / `model_busy`), HTTP body-size series dropped (duration + active kept), span nesting, retries, errors, cancel → `gen_ai_request_outcome=cancelled` (mid-POST, pre-POST, between-attempt; spans not ERROR), stuck-board span shape, GenAI series on `/metrics` after a suggest (success / request / response / parse / illegal_move / timeout + suggest sources), and HTTP scrape status codes for `/suggest` (200 / 422 / 409 / 429).
- `tests/test_suggest_e2e.py` marks real-Ollama cases `e2e` under `APP_ENV=prod` (parametrized legal move + reason, `traceparent` header smoke, GenAI `/metrics` after success, cancel beacon scrape, ASGI disconnect gated on Ollama POST start → `gen_ai_request_outcome=cancelled`; shared fixture rate-limit is a loose budget above the matrix).

## Verification checklist

Run from `server/` after `pip install -e ".[dev]"` (or `uv sync --extra dev`). Goal: conclude the suggest path is solid **without reading implementation files**.

**Scope:** Feature coverage (moves, expectimax, suggest/fallback, cancel, telemetry, client gameplay) already lives in default `pytest` / `npm test`. This checklist **names those layers** and adds gaps around **concurrent LLM admission** (two `429` layers, slot leak, opt-in load) plus **image smokes**. It does not re-test every product feature.

| Layer | Command | Pass if |
|---|---|---|
| Unit + API + concurrency + contract | `pytest` (and `cd ../client && npm test` for UI) | All green; e2e and load skipped |
| Light chaos (disconnect mid-flight) | (included in default `pytest` via `test_cancel.py`) | Cancel A leaves B; while B holds at `max_in_flight=2`, third admits / fourth capacity-429; slot + hard-ceiling token refunded |
| Image smokes (CI `docker run` topology, no Ollama) | CI docker job: `APP_ENV=prod` API + client, then `bash scripts/smoke_api_images.sh` | `/health` ok; `/docs` + `/openapi.json` 404; expectimax via nginx `:5173/suggest`; `/client-events` → 204; `GET /metrics` has `suggest_source=expectimax`, a **joined** `/suggest`+`200` sample line, and `outcome="fail"`; nginx does **not** proxy `/health` or `/metrics` |
| E2E (real Ollama) | `pytest --e2e` | Local Ollama up with `OLLAMA_MODEL`; asserts `source == "llm"` |
| Load / soak (LLM capacity + Expectimax Auto Play cadence) | `pytest --load -m load` | LLM: workers join under hold; accounting closes (incl. cancels + mixed `429` layers); final suggest / gate probe OK. Expectimax: 4 cadence tabs over a **full 60s window** → **0** spend/capacity `429` at default 360 + `EXPECTIMAX_MAX_IN_FLIGHT=4`, `ok` > 120 (and a soft ≥50% of ideal settle+gap throughput); undersized spend trips spend `429`; undersized `max_in_flight=1` trips capacity `429`. Also: Actions → **Run workflow** (`run_load`; optional `load_only`) |

**`429` layers:** spend uses `detail: "too many suggestions"` + `X-Suggest-Limit: spend`; capacity uses `detail: "model busy"` + `X-Suggest-Limit: capacity` + `Retry-After: 1`. Spend `Retry-After` is remaining window seconds (often `60` when just filled) but collapses to `1` near window end — prefer detail / header over `Retry-After` alone. Covered in default CI (`test_suggest_http_contract`, incl. collapse case) and opt-in load.

**Optional Grafana / Phoenix spot-checks** (when series exist): after a local Compose `--profile metrics` drill, confirm `/suggest` status rates and GenAI success/error lines move; Phoenix shows a `suggest` chain for a live LLM call. Not required to trust FakeLLM CI.

## Not built yet

There is no player auth or per-player quota (suggestion and beacon caps are process-wide). The API does not persist games. Expectimax depth stays shallow for latency, not tournament strength.
