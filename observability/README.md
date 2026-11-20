# Observability (Stage 2 metrics)

Phoenix (host, OTLP) owns LLM forensics. Prometheus + Grafana own scrape aggregates from `GET /metrics`.

## Run

With the API (and optional client):

```bash
# from repo root
docker compose --profile dev --profile metrics up
# or: docker compose --profile prod --profile metrics up
```

| UI | URL (loopback) |
| --- | --- |
| API `/metrics` | http://127.0.0.1:8000/metrics |
| Prometheus | http://127.0.0.1:9090 |
| Grafana (GenAI ops dashboard) | http://127.0.0.1:3000/d/game2048-genai |

Grafana allows anonymous Viewer access on loopback. No Alertmanager or retention stack.

Prometheus scrapes Compose DNS name `api:8000` (`dev` and `prod` both use that alias). Generate traffic with `/suggest` (needs host Ollama), then refresh the dashboard.
