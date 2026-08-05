import json
import os
import time

import requests

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


def push_state(state, failed_providers, error):
    if not SUPERVISOR_TOKEN:
        print("SUPERVISOR_TOKEN fehlt, kann Status nicht nach HA pushen.", flush=True)
        return

    attributes = {
        "friendly_name": "AI Gateway aktiver Provider",
        "icon": "mdi:robot",
        "failed_providers": failed_providers,
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


def main():
    while True:
        health_payload, error = check_health()
        active, failed = summarize(health_payload)
        push_state(active or "nicht erreichbar", failed, error)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
