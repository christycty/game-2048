# Architecture

How the client, API, and host model fit together. File-level detail lives under [agents/](agents/README.md).

## System context

```mermaid
flowchart TB
  subgraph host [Host machine]
    Ollama[Ollama :11434]
    subgraph edge [Page origin]
      Client[Client UI]
      Proxy[Vite or nginx /suggest]
    end
    API[API]
  end
  Player((Player)) --> Client
  Client -->|"POST /suggest<br/>same origin"| Proxy
  Proxy --> API
  API -->|"LLM mode"| Ollama
```

**Host-published** ports bind to loopback (`127.0.0.1` and `::1`). `CLIENT_HOST_PORT` maps the page (Vite/nginx); `API_HOST_PORT` maps the **dev** API only (defaults 8000 / 5173 so worktrees can diverge). Prod Compose publishes the client, not the API. The browser calls same-origin `/suggest`; Vite (dev) or nginx (prod Compose) forwards to the API.

## Suggestion path

```mermaid
flowchart TD
  A[Receive board + mode] --> V{Valid payload?}
  V -->|no| U[422]
  V -->|yes| Spend{Spend ceiling?}
  Spend -->|over| TSpend[429 spend<br/>too many suggestions]
  Spend -- ok --> Cap{Mode capacity?}
  Cap -->|full| TBusy[429 capacity + refund spend<br/>model busy]
  Cap -->|slot| B{Legal moves?}
  B -->|none| C[409]
  B -->|yes, expectimax| E[Expectimax thread]
  B -->|yes, llm| P[Attempt 1..N]
  P -->|valid move + reason| G[source: llm]
  P -->|exhausted| H[source: fallback<br/>UI treats as failure]
  E -->|legal search move| I[source: expectimax]
  E -->|illegal / miss| H
  G --> J[Response]
  I --> J
  H --> J
```

Validation (`422`) runs before both per-mode gates (consuming neither the spend ceiling nor an `LLM_MAX_IN_FLIGHT` / `EXPECTIMAX_MAX_IN_FLIGHT` capacity slot), and capacity `429`s refund the spend token before returning `model busy`. `GET /health` never calls Ollama, and Expectimax never calls Ollama. The client offers **Play** (or auto-applies in **Auto Play**) only on usable suggestions—not on fallback, spend/capacity `429`, or transport errors. Auto Play loops suggest → apply → settle client-side, retrying capacity-busy `429`s and model fallbacks briefly while stopping immediately on spend `429`s. **Stop** / takeover aborts the in-flight `/suggest` fetch; on disconnect the server cancels that request’s LLM/search work only (concurrent clients are supported in-process), responds `499`, refunds its spend token, and frees its mode capacity slot. Abort and `499` stay silent in the UI (`AbortError`) while ending Auto Play.

## Coarse module map

```mermaid
flowchart LR
  subgraph client [client/]
    App[App.jsx]
    Hooks[suggest / move / auto / keyboard hooks]
    GameDir[game/]
    SuggestDir[suggest/]
    UI[Board / Score / Actions]
    App --> Hooks
    App --> UI
    Hooks --> GameDir
    Hooks --> SuggestDir
    UI --> GameDir
    UI --> SuggestDir
  end
  subgraph server [server/]
    Main[main.py]
    Limit[rate_limit.py]
    Suggester[suggester.py]
    Moves[moves.py]
    Expectimax[expectimax.py]
    LLM[llm.py]
    Telemetry[telemetry.py]
    Main --> Limit
    Main --> Suggester
    Main --> Telemetry
    Suggester --> Moves
    Suggester --> Expectimax
    Suggester --> LLM
    Suggester --> Telemetry
    LLM --> Telemetry
  end
  SuggestDir --> Main
  Telemetry -.->|OTLP when EXPORT_TRACES| Phoenix[Phoenix]
```

Client owns the playable rules and UI; `App.jsx` wires named hooks for suggest / move / Auto Play / keyboard; pure leaves live under `src/game/` and `src/suggest/` (file map in [agents/client.md](agents/client.md)). Server owns suggestion modes, per-mode process-wide rate limits, legality checks for the coach, expectimax search, the Ollama client (cancel-wait helper in `llm.py`), Phoenix OTLP tracing when `EXPORT_TRACES=true` (opt-in; collector on the host), and always-on `GET /metrics` (optional Compose Prometheus/Grafana). Both sides implement the same slide/merge rules so “legal” means the same thing.

## Stack

| Layer | Choice |
|---|---|
| Client | React 19, Vite, plain JavaScript |
| API | Python 3.12, FastAPI, Pydantic |
| Model | Host Ollama (`OLLAMA_MODEL`, default `gemma4:latest`) |
| Run | Local processes or Docker Compose profiles `dev` / `prod` (+ optional `metrics`) |
| Observability | Phoenix (OTLP traces); `GET /metrics` + optional Prometheus/Grafana; inventory in [agents/telemetry.md](agents/telemetry.md) |
| CI | Docs scripts + link check, lint/test, client build, image build, Compose config checks |

## Deploy profiles

| Profile | What runs |
|---|---|
| `dev` | API with reload + Vite client (API published; Vite proxies `/suggest`) |
| `prod` | API unpublished + nginx static client (`${CLIENT_HOST_PORT}`→80; nginx proxies `/suggest`) |
| `metrics` | Prometheus + Grafana (pair with `dev` or `prod`) |

Ollama and Phoenix stay on the host. Compose reaches them via `host.docker.internal` (override with `COMPOSE_OLLAMA_BASE_URL` / `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`). More runtime edge cases: [agents/runtime.md](agents/runtime.md).
