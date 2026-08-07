#!/usr/bin/env bash
set -e

export PORT="${PORT:-4000}"
export LITELLM_INTERNAL_PORT="${LITELLM_INTERNAL_PORT:-4001}"

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

if [ -f /tmp/gateway-env.sh ]; then
  . /tmp/gateway-env.sh
fi
ENABLE_METRICS="${ENABLE_METRICS:-false}"

GRAFANA_ADMIN_PASSWORD="$(python3 -c "
import json, os
path = '/data/options.json'
if os.path.exists(path):
    print(json.load(open(path)).get('grafana_admin_password') or '')
" 2>/dev/null || true)"

# Nur gesetzt, wenn der Nutzer Grafana ueber eine andere Adresse erreicht als
# das Add-on selbst annimmt (z.B. VPN-Bridge/Reverse-Proxy mit eigenem
# Hostnamen/IP) - Grafanas CSRF-Check vergleicht sonst den Origin-Header
# gegen root_url und lehnt jeden abweichenden Zugriffsweg mit "origin not
# allowed" ab. Ohne diese Optionen bleibt Grafana bei seinen Standardwerten.
GRAFANA_ROOT_URL="$(python3 -c "
import json, os
path = '/data/options.json'
if os.path.exists(path):
    print(json.load(open(path)).get('grafana_root_url') or '')
" 2>/dev/null || true)"

GRAFANA_TRUSTED_HOSTNAMES="$(python3 -c "
import json, os
path = '/data/options.json'
if os.path.exists(path):
    print(json.load(open(path)).get('grafana_trusted_hostnames') or '')
" 2>/dev/null || true)"

PG_PID=""
GRAFANA_PID=""

if [ "$ENABLE_METRICS" = "true" ]; then
  # Postgres und Grafana sind optional (enable_metrics) und duerfen bei
  # Problemen nicht den ganzen Container mit runterreissen - set -e hier
  # bewusst ausgeschaltet, danach wieder aktiviert.
  set +e

  PG_BIN="$(find /usr/lib/postgresql -maxdepth 2 -name bin -type d | sort | tail -1)"
  PGDATA=/data/postgres
  echo "Postgres-Binaries: ${PG_BIN:-<nicht gefunden>}"
  mkdir -p "$PGDATA"
  chown -R postgres:postgres "$PGDATA"

  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initialisiere Postgres-Datenverzeichnis..."
    su postgres -c "$PG_BIN/initdb -D $PGDATA" >/tmp/initdb.log 2>&1
    if [ ! -s "$PGDATA/PG_VERSION" ]; then
      echo "initdb fehlgeschlagen, Ausgabe:" >&2
      cat /tmp/initdb.log >&2
    fi
  fi

  PG_LOG="$PGDATA/postgres.log"
  su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -l $PG_LOG -o '-p 5432 -h 127.0.0.1' start"
  PG_START_STATUS=$?
  if [ "$PG_START_STATUS" -ne 0 ]; then
    echo "pg_ctl start ist mit Code $PG_START_STATUS fehlgeschlagen, $PG_LOG:" >&2
    cat "$PG_LOG" >&2 2>/dev/null
  fi

  i=0
  until su postgres -c "$PG_BIN/pg_isready -h 127.0.0.1 -p 5432" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "Postgres nach 30s nicht bereit - Metrics evtl. nicht nutzbar. $PG_LOG:" >&2
      cat "$PG_LOG" >&2 2>/dev/null
      break
    fi
    sleep 1
  done

  if su postgres -c "$PG_BIN/pg_isready -h 127.0.0.1 -p 5432" >/dev/null 2>&1; then
    su postgres -c "psql -h 127.0.0.1 -p 5432 -tAc \"SELECT 1 FROM pg_roles WHERE rolname='ai_gateway'\"" | grep -q 1 \
      || su postgres -c "psql -h 127.0.0.1 -p 5432 -c \"CREATE ROLE ai_gateway LOGIN PASSWORD 'ai-gateway-internal'\""
    su postgres -c "psql -h 127.0.0.1 -p 5432 -tAc \"SELECT 1 FROM pg_database WHERE datname='ai_gateway'\"" | grep -q 1 \
      || su postgres -c "createdb -h 127.0.0.1 -p 5432 -O ai_gateway ai_gateway"
    echo "Postgres laeuft (intern, Port 5432)."
  fi

  # Debians grafana-Paket hat "provisioning = conf/provisioning" nur
  # auskommentiert in der grafana.ini stehen (relativ, nicht unser
  # /etc/grafana/provisioning) - deshalb hier explizit per Env-Var erzwingen,
  # sonst werden Datasource/Dashboard aus dem Image stillschweigend ignoriert.
  export GF_PATHS_PROVISIONING=/etc/grafana/provisioning
  export GF_PATHS_DATA=/data/grafana/data
  export GF_PATHS_LOGS=/data/grafana/logs
  export GF_PATHS_PLUGINS=/data/grafana/plugins
  mkdir -p "$GF_PATHS_DATA" "$GF_PATHS_LOGS" "$GF_PATHS_PLUGINS"

  # Grafanas CSRF-Check (pkg/middleware/csrf/csrf.go) vergleicht nur den
  # reinen Hostnamen (originURL.Hostname(), also OHNE Schema und Port) des
  # Origin-Headers gegen csrf_trusted_origins - und splittet den Wert an
  # LEERZEICHEN, nicht an Kommas. Schema/Port/Komma in fruehren Versuchen
  # haben deshalb nie gematcht. Beide Werte sind add-on-spezifisch (IP/
  # Hostname des jeweiligen Nutzers) und duerfen daher nicht fest im Image
  # stehen - nur gesetzt, wenn ueber die Optionen konfiguriert.
  if [ -n "$GRAFANA_ROOT_URL" ]; then
    export GF_SERVER_ROOT_URL="$GRAFANA_ROOT_URL"
  fi
  if [ -n "$GRAFANA_TRUSTED_HOSTNAMES" ]; then
    export GF_SECURITY_CSRF_TRUSTED_ORIGINS="$GRAFANA_TRUSTED_HOSTNAMES"
  fi
  if [ -n "$GRAFANA_ADMIN_PASSWORD" ]; then
    export GF_SECURITY_ADMIN_PASSWORD="$GRAFANA_ADMIN_PASSWORD"
  fi

  /usr/share/grafana/bin/grafana server --homepath /usr/share/grafana --config /etc/grafana/grafana.ini &
  GRAFANA_PID=$!

  set -e
fi

# Status-Skript laeuft als Begleitprozess (nicht kritisch: stirbt es, wird nur
# der Status-Sensor nicht mehr aktualisiert, der Proxy selbst laeuft weiter).
python3 status_push.py &
STATUS_PID=$!

# LiteLLM selbst ist nur intern erreichbar (127.0.0.1) - router.py ist der
# einzige nach aussen exponierte Port und entscheidet je Anfrage, welchen
# Provider LiteLLM bedienen soll (Automatik-Kaskade oder harter Override).
litellm --config /app/litellm-config.yaml --port "$LITELLM_INTERNAL_PORT" --host 127.0.0.1 &
LITELLM_PID=$!

python3 router.py &
ROUTER_PID=$!

shutdown() {
  kill "$STATUS_PID" "$LITELLM_PID" "$ROUTER_PID" "$GRAFANA_PID" 2>/dev/null || true
  if [ "$ENABLE_METRICS" = "true" ] && [ -n "$PG_BIN" ]; then
    su postgres -c "$PG_BIN/pg_ctl -D $PGDATA stop" 2>/dev/null || true
  fi
}
trap shutdown TERM INT

wait "$ROUTER_PID"
shutdown
