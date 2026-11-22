# Client-events integrity (beacon trust)

**Status:** Implemented on `client-events-integrity` (worktree `game-2048-client-events-integrity`).  
**Related:** parent `plan/production-practice-review.md` finding 2; cancel-observability (on `main`).

## Is this a security concern?

**Yes, but narrowly.** `/client-events` is not RCE or data exfiltration — it is an **unauthenticated write path into ops metrics**. Anyone who can reach the API can inflate `client_suggest_outcome` (`fail` / `rate_limit` / later `cancel`) and lie to Grafana without spending LLM quota.

For this interview exercise (loopback-published ports, unpublished prod API, no player auth), the practical risk is low. Interview-grade best practice still wants a short, honest story: **trust the browser only as far as the deployment boundary**, and show a cheap integrity control if the API were ever reachable beyond that.

Treat as **ops integrity / metric trust**, not application auth for players.

## Goal

Make client beacon series hard to spam casually, without standing up real user auth or a RUM stack.

## Decisions

1. **Keep the endpoint public to the page** — Same-origin beacons stay; no login.
2. **Do not invent per-player auth** for this app stage.
3. **Prefer a thin integrity gate** over “document and ignore” once cancel beacons land (cancel rates become more interesting to game).
4. **Non-goals:** API keys in the browser as a security boundary (they ship to every client), mTLS, WAF, Alertmanager on beacon spikes.

## Recommended approach (v1)

**Shared process-wide rate limit on `POST /client-events`**, separate from the suggest LLM bucket:

| Piece | Choice |
| --- | --- |
| Cap | Sliding window, e.g. 60 beacons / 60s (tunable via Settings) |
| Over limit | `429` + `Retry-After`; client already ignores beacon failures |
| Labels | Keep outcome enum closed (`fail` \| `rate_limit` \| `cancel`) — already done |
| Tracing | Stay excluded from Phoenix |
| Docs | `telemetry.md`: client rates are best-effort under loopback; rate limit is the integrity control |

Optional later (only if interview narrative wants a second layer): require a short-lived **suggest correlation** (e.g. echo a server-issued request id from the suggest response on the next beacon). Skip for v1 — more moving parts than the value here.

## Implementation sketch

| Layer | Work |
| --- | --- |
| Settings | `CLIENT_EVENTS_RATE_LIMIT_REQUESTS` / window (defaults above) |
| Server | Reuse or twin `SuggestRateLimiter` on `/client-events` before `record_client_suggest_outcome` |
| Client | No UX change (beacon `.catch` already silent) |
| Tests | Cap exhaust → 429 and counter unchanged; under cap still 204 + scrape bump |
| Docs | `telemetry.md` / `runtime.md`: integrity note + defaults |

## Sequencing

After this branch merges (and preferably after cancel-observability unlocks `cancel`). Do **not** block the current client-obs PR on this.

## Verify

- Burst beacons beyond the window → `429`; Grafana series does not climb 1:1 with the burst.
- Normal suggest fail/429/cancel beacons still increment under the cap.
- Suggest rate limit and client-events limit stay independent.
