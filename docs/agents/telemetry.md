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
- **API row:** `/suggest` by status (all codes), Suggest by source, Latency (p50/p95), in-flight HTTP POSTs.
- **Client row:** suggest outcomes (`fail` / `rate_limit` from `/client-events`).
- **LLM row:** success rate, outcomes, error types, duration (p50/p95), tokens.
- Multi-series **rate** panels use **unstacked** lines (each series Y is absolute). Stacked areas make a smaller series look “above” a larger one.
- Legends use **Last \*** = last non-null sample. Rate queries drop `== 0` samples (`> 0`) so idle series do not show a fake `0`; latency / success-rate panels stay empty when there is no traffic.

Excluded from tracing: `/health`, `/metrics`, `/client-events`, `/docs`, `/openapi.json`, `/redoc`.

## Client → server correlation

The browser does **not** run an OpenTelemetry SDK. Each `POST /suggest` from [`client/src/api.js`](../../client/src/api.js) sends a hand-rolled W3C `traceparent` header (`client/src/trace.js`). FastAPI’s OTel instrumentor extracts it so the HTTP + `suggest` + `ollama chat` spans share the client’s `trace_id` in Phoenix.

Coarse client fail / rate-limit counts go to scrape metrics via `POST /client-events` (same-origin; Vite and nginx proxy it). Prompt forensics stay in Phoenix — do not duplicate them in the browser.

App passes `shouldReportOutcome` so abandoned in-flight suggests (stale token after a board-changing move / New Game) do **not** beacon `fail` / `rate_limit`. **Follow-on:** a `cancel` beacon outcome waits on client `AbortSignal` + server disconnect cancel. Do not emit cancel from stale-token ignores either.

`/client-events` is unauthenticated like the rest of the API (no player auth yet). Prod keeps the API unpublished; published ports are loopback-only.

## Where each concern belongs

| Concern | Home | Why |
|---|---|---|
| Prompt / completion text, illegal-move retries, span tree | **Phoenix** | High-cardinality forensics |
| UI action → API → LLM as one trace | **Phoenix** | Client `traceparent` on `/suggest` |
| TTFT, provider total/eval, time-per-output-token | **Phoenix** (span events) | Kept off scrape series on purpose |
| HTTP status rates, API latency | **Grafana** | Aggregates from FastAPI HTTP scrape series |
| Suggest `source` (`llm` / `fallback` / …) | **Grafana** | API-level scrape counter (HTTP 200 ≠ model win) |
| Client fail / rate_limit rates | **Grafana** | `client_suggest_outcome_total` from `/client-events` |
| LLM success / error / timeout rate | **Grafana** | Per-attempt `request_count` scrape series |
| LLM duration p50/p95, token burn | **Grafana** | GenAI histogram scrape series |
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

### Series charted in Grafana (GenAI ops)

Every panel on the provisioned dashboard and the **exact** Prom series suffix it queries. Nothing else on `/metrics` is charted here.

| Panel | Prom series used | Aggregation / labels |
|---|---|---|
| POST /suggest by status | `http_server_duration_milliseconds_count` | `sum by (http_status_code)` · `http_target="/suggest"` · rate `> 0` |
| Suggest by source | `suggest_source_total` | `sum by (suggest_source)` · `llm` \| `fallback` \| `expectimax` · rate `> 0` |
| POST /suggest latency | `http_server_duration_milliseconds_bucket` | `histogram_quantile` p50 + p95 · empty when no `/suggest` traffic |
| In-flight HTTP requests | `http_server_active_requests` | `sum` · `http_method="POST"` (proxy for overlapping `/suggest`; `/health`/`/metrics`/`/client-events` not instrumented) |
| Client suggest outcomes | `client_suggest_outcome_total` | `sum by (outcome)` · `fail` \| `rate_limit` · rate `> 0` |
| LLM request success rate | `gen_ai_client_request_count_total` | `success` rate / total rate; empty when idle (`total rate == 0`) |
| LLM requests by outcome | `gen_ai_client_request_count_total` | `sum by (gen_ai_request_outcome)` · `success` \| `error` \| `timeout` · rate `> 0` |
| LLM errors by type | `gen_ai_client_request_count_total` | `sum by (error_type)` where outcome=`error` · `request` \| `response` \| `parse` \| `illegal_move` · rate `> 0` |
| LLM call duration | `gen_ai_client_operation_duration_seconds_bucket` | `histogram_quantile` p50 + p95 · empty when no body-path calls (excludes timeout/request failures) |
| Token usage rate by type | `gen_ai_client_token_usage_sum` | `sum by (gen_ai_token_type)` · `input` \| `output` · rate `> 0` |

### Intentionally not scraped

| Signal | Why |
|---|---|
| `http.server.request.size` / `http.server.response.size` | Dropped via OTel `View` + `DropAggregation` in `setup_telemetry`. Fixed tiny JSON boards make size panels flat; scrape surface matches charted series. |

HTTP duration / active series still carry host-ish labels (`http_host`, `http_server_name`, `net_host_port`, …). Prefer filtering on `http_target="/suggest"` (duration) or `http_method="POST"` (active) in dashboards and PR Verify screenshots.

### Outcome semantics

**`suggest_source` (one increment per completed suggest response that returns a body):**

| `suggest_source` | Meaning |
|---|---|
| `llm` | Accepted model move + reason |
| `fallback` | Heuristic after LLM attempts exhausted / budget |
| `expectimax` | Expectimax search move |

Not incremented on 429 (rate limit) or 409 (no legal move).

**`request_count` (one increment per Ollama attempt):**

| `gen_ai_request_outcome` | Meaning |
|---|---|
| `success` | Parsed legal move with non-blank reason |
| `error` | Non-timeout failure (`error_type` set) |
| `timeout` | `httpx.TimeoutException` on the Ollama call |

Histograms for duration/tokens record only when usage mapping runs (successful Ollama body path), including attempts that later fail parse/illegal — those attempts still get `request_count` `error`.

**`client_suggest_outcome` (one increment per browser `POST /client-events`):**

| `outcome` | Meaning |
|---|---|
| `fail` | Network error, non-429 HTTP failure, or unusable suggest body |
| `rate_limit` | Suggest returned HTTP 429 |

Not emitted on success. `cancel` is reserved for a later AbortSignal slice.

### Tests (scrape contract)

`tests/test_telemetry.py` asserts **`GET /metrics` text**, not Grafana UI. That is the durable contract Prometheus scrapes and Grafana charts.

| Coverage | Labels / series asserted |
|---|---|
| LLM success path | `gen_ai_request_outcome=success`, duration + token histograms, `suggest_source=llm` |
| LLM failures | `error` + `error_type` = `request` \| `response` \| `parse` \| `illegal_move`; `timeout`; `suggest_source=fallback` |
| Suggest sources | `llm` / `fallback` / `expectimax` (expectimax does not open Ollama) |
| HTTP `/suggest` | `http_server_duration_milliseconds_count` for status `200` / `422` / `409` / `429` (429 does not bump `suggest_source`) |
| Client `traceparent` | Fixed header → `/suggest` spans share that `trace_id` and parent span id |
| Client beacons | `client_suggest_outcome_total` for `fail` / `rate_limit`; `/client-events` not traced |

---

## Not emitted as scrape series

| Signal | Where it lives instead |
|---|---|
| TTFT / load / prompt_eval | Phoenix `First Token Stream Event` |
| time_per_output_token / provider_total / eval | Phoenix `Generation Done` |
| Prompt and completion text | Phoenix LLM span attributes |
| Per-attempt retry narrative | Phoenix `suggest` output `failures` + sibling `ollama chat` spans |
