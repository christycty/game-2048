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
  V -->|yes| R{Hard ceiling?}
  R -->|over| T[429 Retry-After]
  R -->|ok| M{mode}
  M -->|expectimax| B{Legal moves?}
  M -->|llm| Cap{In-flight slot?}
  Cap -->|full| T
  Cap -->|ok| B
  B -->|none| C[409]
  B -->|yes| D{mode work}
  D -->|expectimax| E[Depth-limited search + score reason]
  D -->|llm| F[Ollama chat with retries]
  F -->|valid move + reason| G[source: llm]
  F -->|exhausted| H[source: fallback<br/>UI treats as failure]
  E -->|legal search move| I[source: expectimax]
  E -->|illegal / miss| H
  G --> J[Response]
  I --> J
  H --> J
```

Validation (`422`) runs before the rate-limit gates; invalid bodies do not consume either mode’s hard ceiling or an LLM in-flight slot.

The API stays healthy when Ollama is down (`GET /health` never calls the model). Expectimax never calls Ollama. The client only offers **Play** (or auto-applies under **Auto Play**) when the suggestion is usable—not on fallback, rate limit, or transport errors. Auto Play is entirely client-side: it loops suggest → apply → settle without changing the API. **Stop** / takeover aborts the in-flight `/suggest` fetch; the server watches for disconnect and cancels that request’s LLM/search work only (concurrent clients are supported in-process), responds `499`, refunds that request’s hard-ceiling token, and frees its LLM in-flight slot. The client treats abort and `499` as silent (`AbortError`); a token-matched abort still ends Auto Play so the loop cannot stall.

## Coarse module map

```mermaid
flowchart LR
  subgraph client [client/]
    App[App.jsx]
    Game[game.js]
    Api[api.js]
    UI[Board / Score / Actions]
    App --> Game
    App --> Api
    App --> UI
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
  Api --> Main
  Telemetry -.->|OTLP when EXPORT_TRACES| Phoenix[Phoenix]
```

Client owns the playable rules and UI. Server owns suggestion modes, per-mode process-wide rate limits, legality checks for the coach, expectimax search, the Ollama client, Phoenix OTLP tracing when `EXPORT_TRACES` is on (default; collector optional), and always-on `GET /metrics` (optional Compose Prometheus/Grafana). Both sides implement the same slide/merge rules so “legal” means the same thing.

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

Ollama and Phoenix stay on the host. Compose reaches them via `host.docker.internal` (override with `COMPOSE_OLLAMA_BASE_URL` / `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`).

More runtime edge cases: [agents/runtime.md](agents/runtime.md).
