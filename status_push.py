import json
import os
import time

import requests

from build_litellm_config import MODEL_SPEC
from providers import configured_providers, raw_model_to_provider_map

PORT = os.environ.get("PORT", "4000")
GATEWAY_HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_STATES_URL = "http://supervisor/core/api/states"
POLL_INTERVAL_SECONDS = 60

OPTIONS = {}
if os.path.exists("/data/options.json"):
    with open("/data/options.json", "r", encoding="utf-8") as handle:
        OPTIONS = json.load(handle)

MASTER_KEY = str(OPTIONS.get("gateway_master_key") or "").strip()
ENTITY_ID = str(OPTIONS.get("status_sensor_entity_id") or "sensor.ai_gateway_active_provider").strip()
OVERRIDE_ENTITY_ID = str(OPTIONS.get("provider_override_entity_id") or "input_select.ai_gateway_provider_override").strip()
INTERNAL_METRICS_DB_URL = "postgresql://ai_gateway:ai-gateway-internal@127.0.0.1:5432/ai_gateway"
METRICS_DB_URL = INTERNAL_METRICS_DB_URL if OPTIONS.get("enable_metrics") else ""
AVAILABLE_PROVIDERS = configured_providers(OPTIONS)
# provider-Key -> volles litellm-Modell-Kuerzel (z.B. "groq/llama-3.3-70b-versatile"),
# wie es auch custom_callback.py als "model" ins requests-Log schreibt.
MODEL_SPEC_BY_PROVIDER = {key: MODEL_SPEC[key](OPTIONS)[0] for key in AVAILABLE_PROVIDERS}
RAW_MODEL_TO_PROVIDER = raw_model_to_provider_map(OPTIONS)


def check_health():
    headers = {}
    if MASTER_KEY:
        headers["Authorization"] = f"Bearer {MASTER_KEY}"
    try:
        response = requests.get(GATEWAY_HEALTH_URL, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json(), None
    except Exception as error:  # noqa: BLE001 - jeder Fehler bedeutet "aktuell nicht auswertbar"
        return None, str(error)


def summarize(health_payload):
    """LiteLLM /health liefert healthy_endpoints / unhealthy_endpoints mit den
    konfigurierten model_name-Eintraegen. Daraus den aktiven (ersten gesunden)
    Provider ableiten sowie die Liste der aktuell ausgefallenen."""
    healthy = health_payload.get("healthy_endpoints", []) if health_payload else []
    unhealthy = health_payload.get("unhealthy_endpoints", []) if health_payload else []

    def model_name(entry):
        return entry.get("model") or entry.get("model_name") or "unbekannt"

    active = model_name(healthy[0]) if healthy else None
    failed = [model_name(entry) for entry in unhealthy]
    return active, failed


def provider_status_from_traffic():
    """Ermittelt aktiven/ausgefallenen Provider aus dem zuletzt beobachteten
    echten Request pro Provider in der Metrics-Postgres, statt wie zuvor per
    LiteLLM /health alle 60s eine echte Test-Completion gegen jeden
    konfigurierten Provider zu schicken. Auf dem echten Server hat dieses
    Polling (Faktor 3 Provider x 1440 Polls/Tag) die Tageskontingente von
    Groq (Tokens/Tag) und OpenRouter (Requests/Tag) fast vollstaendig selbst
    verbraucht, bevor ueberhaupt eine echte Assist-Anfrage durchkam. Gibt
    (active, failed) zurueck oder None, wenn keine Metrics-DB verfuegbar ist."""
    if not METRICS_DB_URL or not AVAILABLE_PROVIDERS:
        return None

    try:
        import psycopg2
    except ImportError:
        return None

    try:
        connection = psycopg2.connect(METRICS_DB_URL, connect_timeout=10)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT ON (provider) provider, success FROM requests ORDER BY provider, ts DESC"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except Exception as error:  # noqa: BLE001 - DB-Fehler sollen die Schleife nicht stoppen
        print(f"Konnte Provider-Status nicht aus Metrics-DB lesen: {error}", flush=True)
        return None

    latest_success_by_key = {}
    for raw_model, success in rows:
        key = RAW_MODEL_TO_PROVIDER.get(raw_model)
        if key:
            latest_success_by_key[key] = success

    active = None
    failed = []
    for key in AVAILABLE_PROVIDERS:
        if latest_success_by_key.get(key) is False:
            failed.append(MODEL_SPEC_BY_PROVIDER[key])
        elif active is None:
            active = MODEL_SPEC_BY_PROVIDER[key]

    return active, failed


def read_override_state():
    if not SUPERVISOR_TOKEN:
        return None
    try:
        response = requests.get(
            f"{HA_STATES_URL}/{OVERRIDE_ENTITY_ID}",
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("state")
    except Exception:  # noqa: BLE001 - Override-Anzeige ist rein informativ
        pass
    return None


def push_state(state, failed_providers, error, override_state):
    if not SUPERVISOR_TOKEN:
        print("SUPERVISOR_TOKEN fehlt, kann Status nicht nach HA pushen.", flush=True)
        return

    attributes = {
        "friendly_name": "AI Gateway aktiver Provider",
        "icon": "mdi:robot",
        "failed_providers": failed_providers,
        "override": override_state or "Automatisch (Kaskade)",
        "last_checked": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if error:
        attributes["last_error"] = error

    payload = {"state": state or "unbekannt", "attributes": attributes}
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        requests.post(f"{HA_STATES_URL}/{ENTITY_ID}", headers=headers, json=payload, timeout=10)
    except Exception as error:  # noqa: BLE001 - Push-Fehler sollen die Schleife nicht stoppen
        print(f"Konnte Status nicht nach HA pushen: {error}", flush=True)


def push_metric(entity_id, state, unit, friendly_name, icon):
    if not SUPERVISOR_TOKEN:
        return
    payload = {
        "state": state,
        "attributes": {
            "friendly_name": friendly_name,
            "icon": icon,
            "unit_of_measurement": unit,
        },
    }
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        requests.post(f"{HA_STATES_URL}/{entity_id}", headers=headers, json=payload, timeout=10)
    except Exception as error:  # noqa: BLE001 - Push-Fehler sollen die Schleife nicht stoppen
        print(f"Konnte {entity_id} nicht pushen: {error}", flush=True)


def push_metrics_from_db():
    """Fragt die im selben Add-on-Container laufende Metrics-Postgres nach
    Kennzahlen fuer heute und pusht sie als HA-Sensoren. Ohne enable_metrics
    wird dieser Schritt einfach uebersprungen."""
    if not METRICS_DB_URL:
        return

    try:
        import psycopg2  # lokal importiert, da optional
    except ImportError:
        print("psycopg2 nicht verfuegbar, kann Metrics-Datenbank nicht abfragen.", flush=True)
        return

    try:
        connection = psycopg2.connect(METRICS_DB_URL, connect_timeout=10)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*),
                        COALESCE(SUM(tokens_in + tokens_out), 0),
                        COALESCE(AVG(latency_ms), 0)
                    FROM requests
                    WHERE ts >= date_trunc('day', now())
                    """
                )
                request_count, total_tokens, avg_latency = cursor.fetchone()
        finally:
            connection.close()
    except Exception as error:  # noqa: BLE001 - DB-Fehler sollen die Schleife nicht stoppen
        print(f"Konnte metrics-Datenbank nicht abfragen: {error}", flush=True)
        return

    push_metric("sensor.ai_gateway_requests_today", request_count, "Anfragen", "AI Gateway Anfragen heute", "mdi:counter")
    push_metric("sensor.ai_gateway_tokens_today", total_tokens, "Tokens", "AI Gateway Tokens heute", "mdi:counter")
    push_metric(
        "sensor.ai_gateway_avg_latency_ms",
        round(float(avg_latency), 0),
        "ms",
        "AI Gateway Ø Antwortzeit",
        "mdi:timer-outline",
    )


def main():
    while True:
        traffic_status = provider_status_from_traffic()
        if traffic_status is not None:
            active, failed = traffic_status
            error = None
        else:
            # Fallback ohne Metrics-DB: es gibt keine geloggten echten
            # Requests, aus denen sich der Status ableiten liesse - dann
            # bleibt nur der teurere LiteLLM-/health-Check mit echten
            # Test-Completions.
            health_payload, error = check_health()
            active, failed = summarize(health_payload)
        override_state = read_override_state()
        push_state(active or "nicht erreichbar", failed, error, override_state)
        push_metrics_from_db()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
