# Runtime

How the client, API, and host Ollama run together. Human quick path: [../getting-started.md](../getting-started.md). Every Compose service sits behind a profile: `docker compose up` alone starts nothing.

## Local processes

Typical loop:

1. Ollama on the host at `http://localhost:11434`, with the model named in `OLLAMA_MODEL` (default `gemma4:latest`).
2. API from `server/` on `127.0.0.1:8000`.
3. Client from `client/` on `127.0.0.1:5173` (`npm run dev`).

The page calls **same-origin** `/suggest` by default. Vite proxies that path to `http://127.0.0.1:8000` (override with `API_PROXY_TARGET`). Set `VITE_API_BASE_URL` to an absolute API origin only when you intentionally bypass the proxy. CORS still allows `http://localhost:5173` and `http://127.0.0.1:5173` for that absolute-origin case.

Host API env comes from `server/.env` or the shell. Copy `server/.env.example` for local uvicorn. That file is not read by Compose for the API container.

## Compose

From the repo root:

```bash
cp .env.example .env   # optional; see COMPOSE_OLLAMA_BASE_URL notes below
docker compose --profile dev up
docker compose --profile prod up
```

| Profile | Services | Ports (loopback only) |
|---|---|---|
| `dev` | `dev` (API with reload), `client-dev` (Vite) | API `8000`, client `5173` |
| `prod` | `prod` (API, **unpublished**), `client` (nginx) | client `5173`→container `80` only |

Published ports bind `127.0.0.1` and `::1` so a LAN peer cannot reach them. Prod does **not** publish the API. The page origin stays on 5173; nginx in the client image forwards `/suggest` to `prod:8000` on the Compose network (Docker DNS `127.0.0.11`, 30s read timeout for the suggestion budget). Dev Compose still publishes the API so a host process can call it; `client-dev` sets `API_PROXY_TARGET=http://dev:8000`.

Ollama stays on the host. Inside the API container the default URL is `http://host.docker.internal:11434`. Set `COMPOSE_OLLAMA_BASE_URL` in the root `.env` to override that. Do not set `OLLAMA_BASE_URL` in the root `.env`: that name is for a host uvicorn process (`server/.env.example` uses localhost), and Compose must not replace the container URL with it.

`host.docker.internal` is added via `host-gateway` so Linux Docker Engine can resolve it. Docker Desktop can reach an Ollama bound to `127.0.0.1` at that name. Linux Docker Engine cannot: start that Ollama with `OLLAMA_HOST=0.0.0.0`.

Dev client mounts `./client` and keeps Linux `node_modules` in a named volume. `CHOKIDAR_USEPOLLING=true` keeps Vite watching under Docker. The entrypoint reinstalls modules when `package-lock.json` changes.

### Suggestion rate limit

The API caps suggestions for the **whole process** (default 5 requests per 60 seconds via `SUGGEST_RATE_LIMIT_REQUESTS` / `SUGGEST_RATE_LIMIT_WINDOW_SECONDS`). Over the limit returns `429` with `Retry-After`. The cap is not per browser: in prod the only caller is nginx, and the limit exists to bound model time.

## Images

```bash
docker build -t game-2048-server ./server
docker build -t game-2048-client ./client   # default target is prod (nginx)
```

Server image: `python:3.12-slim`, `pip install -e .`, uvicorn on `0.0.0.0:8000`. Client Dockerfile stages: `dev` (Vite), `build`, `prod` (nginx serving `dist`, SPA `try_files`, plus `/suggest` proxy). Local env files are dockerignored.

## CI

`.github/workflows/ci.yml`:

- Server: install, `ruff format --check`, `ruff check`, `pytest` (e2e off).
- Client: install, lint, test, build.
- Docker: build both images, curl `/health` on the server image without Ollama, check Compose config for the default Ollama URL, loopback port bindings, and that **prod publishes no host ports**.

## Not in this layout

There is no TLS terminator, no auth, and no public demo host. A later host would push the images CI already builds, pin tags, terminate TLS, and keep the model on a private network.
