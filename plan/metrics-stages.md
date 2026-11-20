# Metrics follow-up (after Phoenix traces)

Phoenix owns LLM forensics (prompts, completions, retries, span trees). Metrics own ops aggregates (p95 latency, token burn). Charts may overlap; the systems do not replace each other.

## Stage 1 — thin scrapeable surface (no Grafana)

**Status:** done on `backend-metrics` / `game-2048-metrics`.

**Goal:** Prove metrics ≠ traces. Export what scrapers (Prometheus, Datadog, Grafana later) can read.

**Do:**
- Finish the existing in-process GenAI histograms with a Prometheus reader.
- Expose `/metrics` on the API (or mount the Prometheus ASGI app).
- Keep **two** primary series for interview clarity:
  - `gen_ai.client.operation.duration` (wall seconds per chat call)
  - `gen_ai.client.token.usage` (input/output tokens)
- Optionally keep TTFT / time-per-output-token histograms only if they stay scraped; otherwise drop them when wiring export (they already live on span events).
- Tests: `/metrics` text includes GenAI series after a suggest (success + failure outcomes / `error_type`s + suggest sources) and HTTP status labels for `/suggest` (`200` / `422` / `409` / `429`).
- Docs/PR: Grafana or Datadog can scrape the same endpoint; Phoenix stays on OTLP traces.
- CI: metrics endpoint can stay on; no external Prometheus required.

**Do not (yet):** Compose Prometheus/Grafana, dashboard JSON, Alertmanager.

**Effort:** ~0.3–0.5× the Phoenix tracing work; mostly wiring, little new semantics.

## Stage 2 — Prometheus + Grafana in Compose

**Status:** done on `backend-metrics` / `game-2048-metrics` (`--profile metrics`).

**Goal:** Optional screenshot / live ops UI next to Phoenix.

**Do:**
- Add Prometheus with scrape config pointing at the API `/metrics`.
- Add Grafana with a provisioned Prometheus datasource.
- Dashboard: API (`/suggest` by status unstacked, suggest source, latency) + LLM (success rate, outcomes, error types, p95, tokens).
- Dev/prod Compose profiles and short run notes in the PR or runtime doc.
- Inventory + scrape-contract tests: `docs/agents/telemetry.md` (Phoenix vs scrape series; `/metrics` asserts, not Grafana UI).

**Do not:** Full Datadog-like alert/auth/retention stack. Prometheus Graph is not a product dashboard (Grafana only).

**Effort:** Mostly YAML and Docker networking; less app design than Phoenix. Worth it for a dashboard demo, not required for the production-practice story once Stage 1 lands.

## Decisions frozen with this plan

| Item | Decision |
| --- | --- |
| In-process metrics with no scrape | Temporary; Stage 1 makes them observed or we drop unused instruments |
| Traces vs metrics | Phoenix = forensics; Prometheus/Grafana = aggregates |
| `llm.provider` + `llm.system` both `ollama` | Keep — OpenInference convention, cheap, enables different filters |
