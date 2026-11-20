# Runtime

How the client, API, and host Ollama run together on `main`. Every Compose service sits behind a profile: `docker compose up` alone starts nothing.

## Local processes

Typical loop:

1. Ollama on the host at `http://localhost:11434`, with the model named in `OLLAMA_MODEL` (default `gemma4:latest`).
2. API from `server/` on `127.0.0.1:8000`.
3. Client from `client/` on `127.0.0.1:5173` (`npm run dev`).

The browser calls `http://localhost:8000/suggest` by default. Override with `VITE_API_BASE_URL` at build or Vite start time. The API allowlist matches both `http://localhost:5173` and `http://127.0.0.1:5173`.

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
| `prod` | `prod` (API), `client` (nginx static) | API `8000`, client `5173`→container `80` |

Published ports bind `127.0.0.1` and `::1` so a LAN peer cannot reach them. The prod client stays on host port 5173 so the page origin still matches the CORS allowlist.

Ollama stays on the host. Inside the API container the default URL is `http://host.docker.internal:11434`. Set `COMPOSE_OLLAMA_BASE_URL` in the root `.env` to override that. Do not set `OLLAMA_BASE_URL` in the root `.env`: that name is for a host uvicorn process (`server/.env.example` uses localhost), and Compose must not replace the container URL with it.

`host.docker.internal` is added via `host-gateway` so Linux Docker Engine can resolve it. Docker Desktop can reach an Ollama bound to `127.0.0.1` at that name. Linux Docker Engine cannot: start that Ollama with `OLLAMA_HOST=0.0.0.0`.

Dev client mounts `./client` and keeps Linux `node_modules` in a named volume. `CHOKIDAR_USEPOLLING=true` keeps Vite watching under Docker. The entrypoint reinstalls modules when `package-lock.json` changes.

Neither the Vite image nor the nginx image proxies `/suggest`. The page talks to the API origin directly.

## Images

```bash
docker build -t game-2048-server ./server
docker build -t game-2048-client ./client   # default target is prod (nginx)
```

Server image: `python:3.12-slim`, `pip install -e .`, uvicorn on `0.0.0.0:8000`. Client Dockerfile stages: `dev` (Vite), `build`, `prod` (nginx serving `dist`, SPA `try_files`). Local env files are dockerignored.

## CI

`.github/workflows/ci.yml`:

- Server: install, `ruff format --check`, `ruff check`, `pytest` (e2e off).
- Client: install, lint, test, build.
- Docker: build both images, curl `/health` on the server image without Ollama, check Compose config for the default Ollama URL and loopback port bindings.

## Not in this layout

There is no TLS terminator, no nginx reverse proxy for `/suggest`, and no suggestion rate limit. A later host would push the images CI already builds, pin tags, terminate TLS, and keep the model on a private network.
