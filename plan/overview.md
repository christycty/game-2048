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
| Suggest cancel | Client `AbortSignal`, server disconnect → cancel LLM/expectimax, HTTP `499`, spend + capacity release (PR #14) |
| Client observability | `traceparent` on suggest; `/client-events` `fail` / `rate_limit` / `model_busy` / `cancel`; Grafana Client row (PRs #15, #17, #22) |
| Cancel observability | Cancel beacon + GenAI `cancelled` + dashboard wiring (PR #17) |
| LLM capacity + spend | Hard ceiling vs `LLM_MAX_IN_FLIGHT` gate; distinct 429 signals (PR #18) |
| Multi-client busy UX | Auto Play retries capacity; stops on spend; reject-reason series (PR #22) |
| Gameplay assignment | Random opening two `2`s; hard win at 2048 (PR #19) |
| Auto Play | On selected AI mode (incl. LLM); abort wired on Stop / move / New Game / mode |
| Ollama structured output | Default off; opt-in via env (PR #16) |

Review bar and gaps: [production-practice-review.md](./production-practice-review.md) (partly historical — see Presentability). Metrics history: [metrics-stages.md](./metrics-stages.md) (done).

---

## Active worktrees / branches

| Worktree | Branch | Status |
| --- | --- | --- |
| `game-2048-present` | `presentation-site` | PR #23 — Pages pitch site. Plan: [presentation-site.md](./presentation-site.md) |
| `game-2048-verification` | `verification-ladder` | PR #20 — checklist + contract + opt-in `pytest --load`. Plan: [verification-ladder.md](./verification-ladder.md) |
| `game-2048-client-events-integrity` | `client-events-integrity` | PR #21 — process-wide rate limit on `/client-events`. Plan: [client-events-integrity.md](./client-events-integrity.md) |

---

## Open plans (not done)

| Plan | Depends on | Status |
| --- | --- | --- |
| [verification-ladder.md](./verification-ladder.md) | Rate-limit on `main` (met) | PR #20 open |
| [client-events-integrity.md](./client-events-integrity.md) | Client-obs + cancel on `main` (met) | PR #21 open |
| [presentation-site.md](./presentation-site.md) | None (parallel OK) | PR #23 open — diagrams should match shipped ops |

Merged recently (no longer open): rate-limit layers (#18), cancel-obs (#17), gameplay (#19), multi-client LLM (#22).

---

## Suggested merge / work order

1. ~~**Rate-limit / cancel-obs / gameplay / multi-client**~~ — done (PRs #17–#19, #22).
2. **Verification ladder** — opt-in load + verify-without-reading-code checklist (PR #20).
3. **Client-events integrity** — thin rate limit on `/client-events` (PR #21).
4. **Presentation site** — merge when walkthrough matches shipped ops (PR #23).

---

## Presentability

**Verdict:** READY-WITH-CAVEATS. Product claims match `main`; remaining caveats are demo polish + the two open integrity/verify PRs.

| Caveat | Action |
| --- | --- |
| Cold full demo needs Ollama (+ model) and host Phoenix (not in Compose) | Honest “Try it” on the site + getting-started blurb |
| Beacon spam if API is reachable | Finish PR #21 integrity gate |
| “Verify without reading code” story | Finish PR #20 ladder |
| [production-practice-review.md](./production-practice-review.md) partly historical | Prefer this overview as status board |

Intentionally out of scope (fine to leave): auth/TLS, Alertmanager, multi-instance limits, full RUM/Sentry, model-eval harnesses, deep tournament expectimax.

---

## Ops story at a glance

| Signal | Owner | Today |
| --- | --- | --- |
| LLM forensics (prompts, spans) | Phoenix | On `main` |
| API / GenAI aggregates | Prometheus → Grafana | On `main` |
| Client fail / spend / busy / cancel | `/client-events` → scrape | On `main` |
| Suggest 429 capacity vs spend | `suggest_limit_reject_total` | On `main` |
| LLM concurrency vs spend cap | Capacity gate + hard window | On `main` |
| Beacon integrity rate limit | `/client-events` gate | PR #21 |
| Verify-without-reading-code | Opt-in load + checklist | PR #20 |

---

## Out of scope (accepted for this stage)

Auth/TLS, Alertmanager, multi-instance limits, full browser RUM/Sentry, model-eval harnesses — document rather than silent gaps. See the review’s out-of-scope list.
