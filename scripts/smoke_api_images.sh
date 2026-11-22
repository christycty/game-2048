#!/usr/bin/env bash
# Image-level verification smokes (no Ollama).
#
# Prerequisites: images built; containers running as:
#   - game-2048-server  (EXPORT_TRACES=false; APP_ENV=prod for docs gating)
#   - game-2048-client  (host :5173→80)
# nginx.conf resolves upstream hostname ``prod`` on a shared Docker network.
#
# Topology is CI ``docker run`` (+ invented network/alias), not Compose service
# names. Checks: health, prod docs gate, nginx /suggest + /client-events,
# metrics labels for the suggest, nginx path isolation for /health + /metrics.
set -euo pipefail

NETWORK="${NETWORK:-game-2048-ci}"
CLIENT="${CLIENT_CONTAINER:-game-2048-client}"
SERVER="${SERVER_CONTAINER:-game-2048-server}"
CLIENT_URL="${CLIENT_URL:-http://127.0.0.1:5173}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
SUGGEST_OUT="${SUGGEST_OUT:-/tmp/suggest-nginx.json}"
METRICS_OUT="${METRICS_OUT:-/tmp/metrics-smoke.txt}"

BOARD='{"board":[[2,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],"mode":"expectimax"}'

fail() {
  echo "$*" >&2
  docker logs "$CLIENT" >&2 || true
  docker logs "$SERVER" >&2 || true
  exit 1
}

echo "== health =="
curl -fsS -o /tmp/health-smoke.json "${API_URL}/health" \
  || fail "GET ${API_URL}/health failed"
python3 - <<'PY'
import json
from pathlib import Path
assert json.loads(Path("/tmp/health-smoke.json").read_text()) == {"status": "ok"}
print("health ok")
PY

echo "== prod docs gated =="
docs_code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/docs" || true)"
openapi_code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/openapi.json" || true)"
if [[ "$docs_code" != "404" || "$openapi_code" != "404" ]]; then
  fail "expected /docs and /openapi.json 404 under APP_ENV=prod, got docs=${docs_code} openapi=${openapi_code}"
fi
print_docs="docs=${docs_code} openapi=${openapi_code}"
echo "prod docs gated ok (${print_docs})"

echo "== nginx network =="
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"
docker network disconnect "$NETWORK" "$SERVER" 2>/dev/null || true
docker network connect --alias prod "$NETWORK" "$SERVER"
docker network disconnect "$NETWORK" "$CLIENT" 2>/dev/null || true
docker network connect "$NETWORK" "$CLIENT"

echo "== suggest through nginx (expectimax) =="
ok=0
for _ in $(seq 1 30); do
  if curl -fsS -o "$SUGGEST_OUT" \
    -X POST "${CLIENT_URL}/suggest" \
    -H 'content-type: application/json' \
    -d "$BOARD"; then
    ok=1
    break
  fi
  sleep 1
done
[[ "$ok" == "1" ]] || fail "POST ${CLIENT_URL}/suggest through nginx failed"

python3 - "$SUGGEST_OUT" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
assert data["mode"] == "expectimax", data
assert data["move"] in ("up", "down", "left", "right"), data
assert data["source"] in ("expectimax", "fallback"), data
print("suggest-through-nginx ok:", data["move"], data["source"])
PY

echo "== client-events through nginx =="
events_code="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "${CLIENT_URL}/client-events" \
  -H 'content-type: application/json' \
  -d '{"outcome":"fail"}' || true)"
[[ "$events_code" == "204" ]] || fail "POST ${CLIENT_URL}/client-events expected 204, got ${events_code}"
echo "client-events-through-nginx ok"

echo "== metrics scrape after suggest =="
curl -fsS -o "$METRICS_OUT" "${API_URL}/metrics" \
  || fail "GET ${API_URL}/metrics failed"
python3 - "$METRICS_OUT" <<'PY'
from pathlib import Path
import sys

body = Path(sys.argv[1]).read_text()
assert "suggest_source_total" in body or 'suggest_source="' in body, "missing suggest_source series"
assert 'suggest_source="expectimax"' in body, body[:2000]
# Require /suggest 200 on the same sample line (not a lone status from /health).
suggest_200 = False
for line in body.splitlines():
    if line.startswith("#"):
        continue
    if 'http_target="/suggest"' in line and 'http_status_code="200"' in line:
        suggest_200 = True
        break
assert suggest_200, "no metrics line joins http_target=/suggest with http_status_code=200"
assert 'outcome="fail"' in body, body[:2000]
assert "# TYPE" in body or "http_server_duration_milliseconds" in body
print("metrics scrape ok (expectimax + joined /suggest 200 + client fail beacon)")
PY

echo "== nginx does not proxy /health or /metrics =="
# Only /suggest and /client-events are forwarded; other paths are the SPA.
health_via_nginx="$(curl -sS "${CLIENT_URL}/health" || true)"
metrics_via_nginx="$(curl -sS "${CLIENT_URL}/metrics" || true)"
python3 - "$health_via_nginx" "$metrics_via_nginx" <<'PY'
import json
import sys

health, metrics = sys.argv[1], sys.argv[2]
try:
    payload = json.loads(health)
except json.JSONDecodeError:
    payload = None
assert payload != {"status": "ok"}, "nginx must not proxy /health to the API"
assert "suggest_source=" not in metrics, "nginx must not proxy /metrics to the API"
assert "# TYPE" not in metrics, "nginx must not proxy /metrics to the API"
print("nginx path isolation ok")
PY

echo "smoke_api_images ok"
