#!/usr/bin/env bash
# Flip Docker health for convenience-app or sensor-bridge in the `home` stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SERVICE="${1:-convenience-app}"
MODE="${2:-unhealthy}"

case "$SERVICE" in
  convenience-app) VOL_HINT="app_health" ;;
  sensor-bridge) VOL_HINT="bridge_health" ;;
  *)
    echo "usage: $0 <convenience-app|sensor-bridge> <unhealthy|healthy>" >&2
    exit 2
    ;;
esac

case "$MODE" in
  unhealthy|fail|down) VALUE="fail" ;;
  healthy|ok|up) VALUE="ok" ;;
  *)
    echo "usage: $0 <service> <unhealthy|healthy>" >&2
    exit 2
    ;;
esac

CID="$(docker compose -p home ps -q "$SERVICE")"
if [[ -z "$CID" ]]; then
  echo "service $SERVICE is not running; start with: docker compose -p home up -d --build" >&2
  exit 1
fi

docker compose -p home exec -T "$SERVICE" sh -c "printf '%s\n' '$VALUE' > /data/health"
echo "wrote health=$VALUE for $SERVICE (volume hint: $VOL_HINT)"

# Give Docker HEALTHCHECK a moment to observe.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$CID" 2>/dev/null || echo unknown)"
  if [[ "$MODE" == unhealthy || "$MODE" == fail || "$MODE" == down ]]; then
    [[ "$STATUS" == "unhealthy" ]] && break
  else
    [[ "$STATUS" == "healthy" ]] && break
  fi
  sleep 1
done
echo "docker health status: $STATUS"
