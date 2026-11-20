# Telemetry inventory

Canonical list of what this API emits and **where to look**. Implementation: `server/app/telemetry.py`, FastAPI OTel instrumentor, `GET /metrics`. Compose scrape UI: [runtime.md](runtime.md). Suggest pipeline context: [server.md](server.md).

## Why these pieces

| Piece | Role |
|---|---|
| **API `/metrics`** | Source of truth for scrapeable series (Prometheus text). Always on. |
| **Prometheus** | Scrapes `/metrics`, **stores** time series, evaluates PromQL. Grafana does not store history. Without a TSDB (Prometheus here, or Datadog/etc.), Grafana has nothing durable to chart. Its Graph UI is ad-hoc debug only—not a product dashboard. |
| **Grafana** | Queries Prometheus and draws the GenAI ops dashboard. Day-to-day ops UI. |
| **Phoenix** | Receives OTLP **traces**. Forensics: prompts, completions, retries, per-call timings as span events. |

Charts may overlap in *topic* (e.g. latency). Systems do not replace each other: HTTP `200` can still mean LLM fallback—API status ≠ model outcome.

## What a “scrape series” is

A **scrape series** is a metric the process exposes on `GET /metrics` in Prometheus text format so an external scraper (Compose Prometheus, Datadog agent, …) can pull it on an interval and keep history.

| Property | Scrape series (Prom / Grafana) | Traces / span events (Phoenix) |
|---|---|---|
| How it leaves the process | Pull: scraper hits `/metrics` | Push: OTLP export when `EXPORT_TRACES=true` |
| Cardinality | Low, stable labels (status, outcome, source, model) | High (full prompt/completion text per call) |
| Best for | Rates, p95, “is fallback rising?” over hours | “Why did *this* suggest fail?” one request |
| If the process restarts | Counters reset; history already in Prometheus | In-flight spans may flush; forensics stay in Phoenix |
| Cost of a bad label | Explodes series count in the TSDB | Explodes storage/UI noise in the trace store |

**Rule of thumb:** if you would chart it or alert on it, it belongs as a scrape series. If you need the raw prompt, retry narrative, or TTFT for one call, keep it on the span (not scraped).

We intentionally **do not** scrape TTFT / time-per-output-token / prompt text: those stay Phoenix span events/attributes so `/metrics` stays cheap and dashboards stay readable.

**Grafana charting:**
- **API row:** `/suggest` by status (all codes), Suggest by source, Latency (p50/p95).
- **LLM row:** success rate, outcomes, error types, duration, tokens.
- Multi-series **rate** panels use **unstacked** lines (each series Y is absolute). Stacked areas make a smaller series look “above” a larger one.

Excluded from tracing: `/health`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`.

## Where each concern belongs

| Concern | Home | Why |
|---|---|---|
| Prompt / completion text, illegal-move retries, span tree | **Phoenix** | High-cardinality forensics |
| TTFT, provider total/eval, time-per-output-token | **Phoenix** (span events) | Kept off scrape series on purpose |
| HTTP status rates, API latency | **Grafana** | Aggregates from FastAPI HTTP scrape series |
| Suggest `source` (`llm` / `fallback` / …) | **Grafana** | API-level scrape counter (HTTP 200 ≠ model win) |
| LLM success / error / timeout rate | **Grafana** | Per-attempt `request_count` scrape series |
| LLM duration p95, token burn | **Grafana** | GenAI histogram scrape series |
| Ad-hoc PromQL / “is scrape up?” | Prometheus Graph | Not a product dashboard |

---

## Phoenix (OTLP traces)

Export when `EXPORT_TRACES=true` (Compose/dev/prod default; CI sets `false`).

### Spans

| Span name | Kind | When | Notable attributes / I/O |
|---|---|---|---|
| `POST /suggest` | CHAIN (HTTP server) | Every `/suggest` | Request/response JSON after the rate-limit gate (429 has no I/O attrs); ERROR on 409. Stuck board never opens `suggest`. |
| `suggest` | CHAIN | Suggest pipeline (past rate limit, board has legal moves) | Input: `mode`, `board`, `legal`. Output: suggest result; may include `failures` after retries. Also sets `input.mime_type` / `output.mime_type`. |
| `ollama chat` | LLM | Each Ollama attempt | See LLM attributes below; status ERROR on request/parse/illegal-move |

Expectimax / rate-limit-before-model paths do not open `ollama chat`. Each HTTP `/suggest` may increment `request_count` once per Ollama attempt (retries → multiple).

### `ollama chat` attributes

| Attribute (OpenInference / custom) | When set |
|---|---|
| `openinference.span.kind` = `LLM` | Always on this span |
| `llm.provider` / `llm.system` = `ollama` | Always |
| `llm.model_name` | Request model |
| `llm.invocation_parameters` | Structured-output flag, timeout, stream=false |
| `llm.input_messages.0.{role,content}` + `input.value` | Prompt (also on failed requests) |
| `llm.output_messages.0.{role,content}` + `output.value` | Model reply when a body exists |
| `llm.finish_reason` | From Ollama `done_reason` when present |
| `llm.token_count.prompt` / `.completion` / `.total` | From Ollama counts when present |
| `llm.token_count.prompt_details.cache_read` | When cache read &gt; 0 |
| `llm.response.model_name` | When response model ≠ request model |
| Exception + ERROR status | Request failure, bad JSON, illegal move, etc. |

### Span events (not scrape series)

| Event | Attributes | Notes |
|---|---|---|
| `First Token Stream Event` | `ttft`, optional `load`, `prompt_eval` | Synthetic TTFT for non-streaming chat (OpenInference event name; not a real stream) |
| `Generation Done` | `provider_total`, `eval`, `time_per_output_token` | Provider-side timings |

---

## Scrape series (`GET /metrics`)

Always on. Names below are the **Prometheus text** forms (OTel dots → underscores; counters get `_total`; histograms expose `_bucket` / `_count` / `_sum`).

### First-class (dashboarded)

| Series | Kind | Source | Labels (useful) | Grafana (GenAI ops) |
|---|---|---|---|---|
| `http_server_duration_milliseconds_*` | Histogram | FastAPI instrumentor | `http_target`, `http_status_code` | `/suggest` by status; latency p50/p95 |
| `suggest_source_total` | Counter | App (`suggest.source`) | `suggest_source` = `llm` \| `fallback` \| `expectimax-stub` | Suggest by source |
| `gen_ai_client_request_count_total` | Counter | App (`gen_ai.client.request_count`) | `gen_ai_request_outcome` = `success` \| `error` \| `timeout`; optional `error_type` (`request` / `response` / `parse` / `illegal_move`); model / provider | LLM success rate (empty when idle); requests by outcome; errors by type |
| `gen_ai_client_operation_duration_seconds_*` | Histogram | App (`gen_ai.client.operation.duration`) | model / provider / operation | LLM call duration p95 — recorded on Ollama **body** path (includes later parse/illegal failures; excludes timeout/request failures) |
| `gen_ai_client_token_usage_*` | Histogram | App (`gen_ai.client.token.usage`) | `gen_ai_token_type` = `input` \| `output` | Token usage rate by type |

### Present but not charted (noise / secondary)

| Series | Kind | Notes |
|---|---|---|
| `http_server_active_requests` | Gauge | In-flight HTTP |
| `http_server_request_size_bytes_*` | Histogram | Request body size |
| `http_server_response_size_bytes_*` | Histogram | Response body size |

HTTP series also carry high-cardinality host labels (`http_host`, `http_server_name`, `net_host_port`, …). Prefer filtering on `http_target="/suggest"` in dashboards and PR Verify screenshots.

### Outcome semantics

**`suggest_source` (one increment per completed suggest response that returns a body):**

| `suggest_source` | Meaning |
|---|---|
| `llm` | Accepted model move + reason |
| `fallback` | Heuristic after LLM attempts exhausted / budget |
| `expectimax-stub` | Expectimax mode stub |

Not incremented on 429 (rate limit) or 409 (no legal move).

**`request_count` (one increment per Ollama attempt):**

| `gen_ai_request_outcome` | Meaning |
|---|---|
| `success` | Parsed legal move with non-blank reason |
| `error` | Non-timeout failure (`error_type` set) |
| `timeout` | `httpx.TimeoutException` on the Ollama call |

Histograms for duration/tokens record only when usage mapping runs (successful Ollama body path), including attempts that later fail parse/illegal — those attempts still get `request_count` `error`.

### Tests (scrape contract)

`tests/test_telemetry.py` asserts **`GET /metrics` text**, not Grafana UI. That is the durable contract Prometheus scrapes and Grafana charts.

| Coverage | Labels / series asserted |
|---|---|
| LLM success path | `gen_ai_request_outcome=success`, duration + token histograms, `suggest_source=llm` |
| LLM failures | `error` + `error_type` = `request` \| `response` \| `parse` \| `illegal_move`; `timeout`; `suggest_source=fallback` |
| Suggest sources | `llm` / `fallback` / `expectimax-stub` (expectimax does not open Ollama) |
| HTTP `/suggest` | `http_server_duration_milliseconds_count` for status `200` / `422` / `409` / `429` (429 does not bump `suggest_source`) |

---

## Not emitted as scrape series

| Signal | Where it lives instead |
|---|---|
| TTFT / load / prompt_eval | Phoenix `First Token Stream Event` |
| time_per_output_token / provider_total / eval | Phoenix `Generation Done` |
| Prompt and completion text | Phoenix LLM span attributes |
| Per-attempt retry narrative | Phoenix `suggest` output `failures` + sibling `ollama chat` spans |
