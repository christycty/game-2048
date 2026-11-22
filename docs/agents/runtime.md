# Runtime

How the client, API, and host Ollama run together. Human quick path: [../getting-started.md](../getting-started.md). Every Compose service sits behind a profile: `docker compose up` alone starts nothing.

## Local processes

Typical loop:

1. Ollama on the host at `http://localhost:11434`, with the model named in `OLLAMA_MODEL` (default `gemma4:latest`).
2. API from `server/` on `127.0.0.1:${API_HOST_PORT}` (default `8000`).
3. Client from `client/` on `127.0.0.1:${CLIENT_HOST_PORT}` (default `5173`; Vite loads those names from the repo-root `.env`).

The page calls **same-origin** `/suggest` (and `/client-events`) by default. Vite proxies those paths to `http://127.0.0.1:${API_HOST_PORT}` (override with `API_PROXY_TARGET`). Set `VITE_API_BASE_URL` to an absolute API origin only when you intentionally bypass the proxy. CORS allows `http://localhost:${CLIENT_HOST_PORT}` and `http://127.0.0.1:${CLIENT_HOST_PORT}` for that absolute-origin case.

Host API env comes from `server/.env` or the shell. Copy `server/.env.example` for local uvicorn. That file is not read by Compose for the API container. Keep `CLIENT_HOST_PORT` in sync with the page port when you use absolute API URLs.

## Worktrees and ports

Multiple checkouts on one machine collide on Compose project name and on host ports. In the repo-root `.env` (from `.env.example`):

| Variable | Role |
|---|---|
| `COMPOSE_PROJECT_NAME` | Distinct Compose project (networks, volumes, container names) |
| `API_HOST_PORT` | Host loopback port published for the **dev** API (default `8000`) |
| `CLIENT_HOST_PORT` | Host loopback port for Vite / nginx (default `5173`); also drives API CORS |
| `PROMETHEUS_HOST_PORT` | Host loopback port for Prometheus (default `9090`) |
| `GRAFANA_HOST_PORT` | Host loopback port for Grafana (default `3000`) |
| `COMPOSE_OLLAMA_BASE_URL` | Optional override for the API container’s Ollama URL (default `http://host.docker.internal:11434`) |
| `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT` | Optional override for the API container’s Phoenix base URL (default `http://host.docker.internal:6006`) |

Container-listen ports stay `8000` (API), `5173` / `80` (client), `9090` / `3000` (metrics). Only the **host** mapping moves.

Default LLM attempt timeout is 20s and suggestion budget 40s (budget must cover two attempts). Phoenix export: host uvicorn respects `EXPORT_TRACES` / `PHOENIX_COLLECTOR_ENDPOINT` from `server/.env` (or the shell). Compose `dev` / `prod` API services hardcode `EXPORT_TRACES=true` and inject `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT` the same way they do for Ollama—turning export off for Compose requires changing `docker-compose.yml`. Optional `PHOENIX_API_KEY` is passed through Compose with the same bearer rules as the host. The API stays healthy if the collector is down.

## Compose

From the repo root:

```bash
cp .env.example .env   # then set COMPOSE_PROJECT_NAME + ports for this worktree
docker compose --profile dev up
docker compose --profile prod up
# optional scrapers alongside either API profile:
docker compose --profile dev --profile metrics up
```

| Profile | Services | Ports (loopback only) |
|---|---|---|
| `dev` | `dev` (API with reload), `client-dev` (Vite) | API `${API_HOST_PORT}`→8000, client `${CLIENT_HOST_PORT}`→5173 |
| `prod` | `prod` (API, **unpublished**), `client` (nginx) | client `${CLIENT_HOST_PORT}`→80 only |
| `metrics` | `prometheus`, `grafana` (pair with `dev` or `prod`) | Prometheus `${PROMETHEUS_HOST_PORT}`→9090, Grafana `${GRAFANA_HOST_PORT}`→3000 |

Published ports bind `127.0.0.1` and `::1` so a LAN peer cannot reach them. Prod does **not** publish the API. The page origin is the client host port; nginx in the client image forwards `/suggest` and `/client-events` to `prod:8000` on the Compose network (Docker DNS `127.0.0.11`, 50s read timeout on `/suggest` over the 40s suggestion budget). Dev Compose still publishes the API so a host process can call it; `client-dev` sets `API_PROXY_TARGET=http://dev:8000`.

Ollama stays on the host. Inside the API container the default URL is `http://host.docker.internal:11434`. Set `COMPOSE_OLLAMA_BASE_URL` in the root `.env` to override that. Do not set `OLLAMA_BASE_URL` in the root `.env`: that name is for a host uvicorn process (`server/.env.example` uses localhost), and Compose must not replace the container URL with it. Same rule for Phoenix: use `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`, not `PHOENIX_COLLECTOR_ENDPOINT`, in the root `.env`.

Phoenix (OTLP traces) also stays on the host by default (`http://host.docker.internal:6006`). Override with `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`. Do not set `PHOENIX_COLLECTOR_ENDPOINT` in the root `.env` for the same reason as Ollama. Dev and prod export traces (`EXPORT_TRACES=true`); CI sets `EXPORT_TRACES=false` on the API image.

`host.docker.internal` is added via `host-gateway` so Linux Docker Engine can resolve it. Docker Desktop can reach an Ollama bound to `127.0.0.1` at that name. Linux Docker Engine cannot: start that Ollama with `OLLAMA_HOST=0.0.0.0`.

Dev client mounts `./client` and keeps Linux `node_modules` in a named volume. `CHOKIDAR_USEPOLLING=true` keeps Vite watching under Docker. The entrypoint reinstalls modules when `package-lock.json` changes.

### Suggestion rate limit

The API caps suggestions **per mode** for the whole process (shared window via `SUGGEST_RATE_LIMIT_WINDOW_SECONDS`, default 60s):

| Mode | Env | Default |
|---|---|---|
| LLM | `SUGGEST_RATE_LIMIT_REQUESTS` | 5 |
| Expectimax | `SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS` | 30 |

Over the limit returns `429` with `Retry-After`. The cap is not per browser: in prod the only caller is nginx. The LLM bucket bounds model time; Expectimax is higher so Auto Play can run without spending the LLM quota. A mid-run cancel (`499`) releases **that request’s** rate-limit token so Stop/disconnect does not burn the mode cap or a sibling’s hit.

### Metrics profile

`GET /metrics` on the API is always on (Prometheus text). Pair `--profile metrics` with `dev` or `prod` to scrape it:

- Prometheus scrapes Compose DNS `api:8000` (`dev` and `prod` both publish that alias).
- Grafana **GenAI ops** (`/d/game2048-genai`): API row (`/suggest` by status, suggest by source, latency p50/p95, in-flight POSTs), Client row (fail / rate_limit / cancel beacons), and LLM row (success rate excluding cancelled, outcomes incl. cancelled, error types, duration p50/p95, tokens). Unstacked rate lines; legend **Last \*** skips idle zeros. Inventory: [telemetry.md](telemetry.md).
- Anonymous Viewer access on loopback; no Alertmanager or retention stack. Prometheus Graph is ad-hoc only.

Config lives under `observability/` (`prometheus.yml`, Grafana provisioning).

## Images

```bash
docker build -t game-2048-server ./server
docker build -t game-2048-client ./client   # default target is prod (nginx)
```

Server image: `python:3.12-slim`, `pip install -e .`, uvicorn on `0.0.0.0:8000`. Client Dockerfile stages: `dev` (Vite), `build`, `prod` (nginx serving `dist`, SPA `try_files`, plus `/suggest` and `/client-events` proxies). Local env files are dockerignored.

## CI

`.github/workflows/ci.yml` (pull requests only; four parallel jobs):

- Docs (Python 3.12): script unit tests, `check_doc_links.py` (**fails** on broken links), freshness nudge (`check_docs_freshness.py`, warn-only).
- Server: install, `ruff format --check`, `ruff check`, `pytest` (e2e off; `EXPORT_TRACES` off for tests). Metrics stay on regardless.
- Client (Node 22): install, lint, test, build.
- Docker: build both images; client image smoke (`id="root"`); curl `/health` on the server image without Ollama (`EXPORT_TRACES=false`); Compose config checks for default Ollama/Phoenix URLs on `host.docker.internal`, loopback publish binds, **prod API unpublished** (client still publishes `${CLIENT_HOST_PORT}`→80), the `api` alias, metrics-profile ports, `API_HOST_PORT` / `CLIENT_HOST_PORT` / `PROMETHEUS_HOST_PORT` / `GRAFANA_HOST_PORT` remaps, Compose API `EXPORT_TRACES=true`, and `COMPOSE_OLLAMA_BASE_URL` / `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT` overrides.

## Not in this layout

There is no TLS terminator, no auth, and no public demo host. Metrics Compose has no Alertmanager or long retention. A later host would push the images CI already builds, pin tags, terminate TLS, and keep the model on a private network.
