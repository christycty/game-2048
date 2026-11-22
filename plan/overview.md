# Project overview (current state)

High-level map of the 2048 + AI suggest service: what is on `main`, what is in flight, and how the plans fit together. Detail lives in the linked plan docs; this file is the status board.

**Product:** single-player 2048 with LLM / Expectimax suggest, local/Compose ops (Phoenix traces, Prometheus/Grafana aggregates).

**Layout:** `game-2048-parent/` holds shared `plan/` plus git worktrees of the same repo under sibling dirs.

---

## On `main` (shipped)

| Area | Notes |
| --- | --- |
| Core suggest API + client | Validation, CORS, rate limits, LLM budgets/retries/fallback, CI |
| Metrics Stages 1–2 | `/metrics`, Compose Prometheus/Grafana (`--profile metrics`), GenAI ops dashboard |
| Suggest cancel | Client `AbortSignal`, server disconnect → cancel LLM/expectimax, HTTP `499`, rate-limit refund (PR #14) |
| Client observability | `traceparent` on suggest, `/client-events` fail/rate_limit beacons, Grafana Client row (PR #15). Cancel beacon still reserved/`422` |
| Auto Play | On selected AI mode (incl. LLM); abort wired on Stop / move / New Game / mode |
| Ollama structured output | Default off; opt-in via env (PR #16) |

Review bar and gaps: [production-practice-review.md](./production-practice-review.md) (partly historical — see Presentability). Metrics history: [metrics-stages.md](./metrics-stages.md) (done).

---

## Active worktrees / branches

| Worktree | Branch | Status |
| --- | --- | --- |
| `game-2048` | `llm-rate-limit-layers` | WIP: raised LLM hard ceiling + `max_in_flight` capacity gate. Plan: [llm-rate-limit-layers.md](./llm-rate-limit-layers.md) |
| `game-2048-cancel-obs` | `cancel-observability` | WIP: cancel beacon + GenAI `cancelled` + Grafana. Plan: [cancel-observability.md](./cancel-observability.md) |
| `game-2048-present` | `presentation-site` | Pitch / GitHub Pages site. Plan: [presentation-site.md](./presentation-site.md) |
| `game-2048-client-obs` | `client-observability` | Merged via PR #15; safe to remove when convenient |

Leftover dirs (`game-2048-auto-play`, `game-2048-metrics`) are not active worktrees; their work is already on `main`. Remove when convenient so the parent folder doesn’t look unfinished.

---

## Open plans (not done)

| Plan | Depends on | Status |
| --- | --- | --- |
| [llm-rate-limit-layers.md](./llm-rate-limit-layers.md) | Cancel on `main` (done) | Implementing now |
| [cancel-observability.md](./cancel-observability.md) | Cancel + client-obs on `main` (done) | Implementing on `game-2048-cancel-obs` |
| [client-events-integrity.md](./client-events-integrity.md) | Client-obs (prefer after cancel-obs unlocks `cancel`) | Agreed follow-up |
| [presentation-site.md](./presentation-site.md) | None (parallel OK) | Starting — Pages pitch layer + narrative polish |

Ops residual and the presentation site can proceed in parallel. Prefer diagram copy that matches post-residual reality, or label in-flight pieces explicitly.

---

## Suggested merge / work order

1. **Finish & merge `llm-rate-limit-layers`** — builds only on cancel already on `main`; unlocks safer LLM Auto Play under load.
2. ~~**Merge `client-observability`**~~ — done (PR #15).
3. **Cancel observability** — allow beacon `cancel`, GenAI `cancelled` outcome, Grafana panels ([cancel-observability.md](./cancel-observability.md)).
4. **Client-events integrity** — thin rate limit on `/client-events` ([client-events-integrity.md](./client-events-integrity.md)).
5. **Presentation site + presentability polish** — [presentation-site.md](./presentation-site.md) (can scaffold anytime; merge when diagrams match shipped ops).

---

## Presentability (after residual ops)

**Verdict:** READY-WITH-CAVEATS once residual ops land. Product claims already match reality; caveats are narrative/demo polish.

| Caveat | Action |
| --- | --- |
| Cold full demo needs Ollama (+ model) and host Phoenix (not in Compose) | Honest “Try it” on the site + getting-started blurb |
| `AGENTS.md` still says “traces only—no scrape `/metrics`” | Fix on presentation or docs PR |
| [production-practice-review.md](./production-practice-review.md) stale vs shipped metrics/cancel | Refresh or mark historical; use this overview as status board |
| Parent leftover worktree dirs | Delete when convenient |
| Cancel demo story weak until cancel-obs | Finish [cancel-observability.md](./cancel-observability.md) before calling ops complete |

Intentionally out of scope (fine to leave): auth/TLS, Alertmanager, multi-instance limits, full RUM/Sentry, model-eval harnesses, deep tournament expectimax.

---

## Ops story at a glance

| Signal | Owner | Today |
| --- | --- | --- |
| LLM forensics (prompts, spans) | Phoenix | On `main` |
| API / GenAI aggregates | Prometheus → Grafana | On `main` |
| Client fail / 429 rates | `/client-events` → scrape | On `main` (PR #15) |
| Client cancel rate + GenAI `cancelled` | Beacons + metrics | `cancel-observability` worktree |
| LLM concurrency vs spend cap | Capacity gate + hard window | `llm-rate-limit-layers` WIP |

---

## Out of scope (accepted for this stage)

Auth/TLS, Alertmanager, multi-instance limits, full browser RUM/Sentry, model-eval harnesses — document rather than silent gaps. See the review’s out-of-scope list.
