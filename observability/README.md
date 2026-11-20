# Observability configs

Compose files for the optional `--profile metrics` stack (Prometheus + Grafana).

**Canonical run notes, ports, and env pitfalls:** [docs/agents/runtime.md](../docs/agents/runtime.md).  
**API series and settings:** [docs/agents/server.md](../docs/agents/server.md).

```bash
docker compose --profile dev --profile metrics up
# Grafana GenAI ops: http://127.0.0.1:3000/d/game2048-genai
```
