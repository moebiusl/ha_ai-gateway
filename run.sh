#!/usr/bin/env bash
set -e

export PORT="${PORT:-4000}"

load_token_file() {
  if [ -z "$SUPERVISOR_TOKEN" ] && [ -f "$1" ]; then
    SUPERVISOR_TOKEN="$(cat "$1")"
    export SUPERVISOR_TOKEN
  fi
}

load_token_file /var/run/s6/container_environment/SUPERVISOR_TOKEN
load_token_file /var/run/s6/container_environment/HASSIO_TOKEN
load_token_file /run/s6/container_environment/SUPERVISOR_TOKEN
load_token_file /run/s6/container_environment/HASSIO_TOKEN

if [ -z "$SUPERVISOR_TOKEN" ]; then
  echo "SUPERVISOR_TOKEN fehlt. homeassistant_api/hassio_api muessen im Add-on aktiviert sein." >&2
fi

cd /app
python3 build_litellm_config.py

# Status-Skript laeuft als Begleitprozess (nicht kritisch: stirbt es, wird nur
# der Status-Sensor nicht mehr aktualisiert, der Proxy selbst laeuft weiter).
python3 status_push.py &
STATUS_PID=$!

litellm --config /tmp/litellm-config.yaml --port "$PORT" --host 0.0.0.0 &
LITELLM_PID=$!

shutdown() {
  kill "$STATUS_PID" "$LITELLM_PID" 2>/dev/null || true
}
trap shutdown TERM INT

wait "$LITELLM_PID"
shutdown
