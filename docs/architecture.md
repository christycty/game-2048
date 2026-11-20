# Architecture

How the client, API, and host model fit together. File-level detail lives under [agents/](agents/README.md).

## System context

```mermaid
flowchart TB
  subgraph host [Host machine]
    Ollama[Ollama :11434]
    subgraph processes [Local or Compose]
      Client[Client :5173]
      API[API :8000]
    end
  end
  Player((Player)) --> Client
  Client -->|"POST /suggest<br/>no Vite/nginx proxy"| API
  API -->|"LLM mode"| Ollama
```

Ports bind to loopback. The browser talks to the API origin directly (`VITE_API_BASE_URL`, default `http://localhost:8000`).

## Suggestion path

```mermaid
flowchart TD
  A[Receive board + mode] --> B{Legal moves?}
  B -->|none| C[409]
  B -->|yes| D{mode}
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

The API stays healthy when Ollama is down (`GET /health` never calls the model). Expectimax never calls Ollama. The client only offers **Play** when the suggestion is usable—not on fallback or transport errors.

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
    Suggester[suggester.py]
    Moves[moves.py]
    Expectimax[expectimax.py]
    LLM[llm.py]
    Main --> Suggester
    Suggester --> Moves
    Suggester --> Expectimax
    Suggester --> LLM
  end
  Api --> Main
```

Client owns the playable rules and UI. Server owns suggestion modes, legality checks for the coach, expectimax search, and the Ollama client. Both sides implement the same slide/merge rules so “legal” means the same thing.

## Stack

| Layer | Choice |
|---|---|
| Client | React 19, Vite, plain JavaScript |
| API | Python 3.12, FastAPI, Pydantic |
| Model | Host Ollama (`OLLAMA_MODEL`, default `gemma4:latest`) |
| Run | Local processes or Docker Compose profiles `dev` / `prod` |
| CI | Lint, test, image build, Compose config checks |

## Deploy profiles

| Profile | What runs |
|---|---|
| `dev` | API with reload + Vite client |
| `prod` | API + nginx static client (still on host port 5173 for CORS) |

Ollama always stays on the host. Compose reaches it via `host.docker.internal` (override with `COMPOSE_OLLAMA_BASE_URL`).

More runtime edge cases: [agents/runtime.md](agents/runtime.md).
