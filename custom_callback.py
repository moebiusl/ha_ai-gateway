"""LiteLLM-Proxy-Callback fuers Logging in den metrics/-Stack.

Der eingebaute "generic_api"-Callback von LiteLLM ist eine
Enterprise-Funktion (Lizenzpflicht) - das ist beim Testen aufgefallen.
Diese Datei ist der kostenlose Ersatz: eine eigene CustomLogger-Klasse,
die LiteLLM direkt (im selben Prozess) aufruft. Wird ueber
litellm_settings.callbacks: custom_callback.proxy_handler_instance
in der generierten litellm-config.yaml registriert (siehe
build_litellm_config.py). Muss laut LiteLLM-Doku im selben Verzeichnis
wie die config.yaml liegen.
"""

import json
import os
import time

import httpx
from litellm.integrations.custom_logger import CustomLogger

OPTIONS_PATH = "/data/options.json"


def _read_metrics_webhook_url():
    if not os.path.exists(OPTIONS_PATH):
        return ""
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
            options = json.load(handle)
        return str(options.get("metrics_webhook_url") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _usage_dict(response_obj):
    usage = _get(response_obj, "usage")
    if usage is None:
        return {}
    return {
        "prompt_tokens": _get(usage, "prompt_tokens", 0),
        "completion_tokens": _get(usage, "completion_tokens", 0),
    }


def _response_payload(response_obj):
    choices = _get(response_obj, "choices")
    if isinstance(choices, list) and choices:
        message = _get(choices[0], "message")
        content = _get(message, "content")
        if content:
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return None


def _iso(ts):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts.timestamp())) + "Z"
    except Exception:  # noqa: BLE001
        return None


class MetricsWebhookLogger(CustomLogger):
    async def _send(self, payload):
        webhook_url = _read_metrics_webhook_url()
        if not webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(webhook_url, json=payload)
        except Exception as error:  # noqa: BLE001 - Logging darf den Request nicht stoeren
            print(f"[metrics] Konnte Anfrage nicht an {webhook_url} loggen: {error}", flush=True)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        payload = {
            "model": kwargs.get("model"),
            "messages": kwargs.get("messages"),
            "response": _response_payload(response_obj),
            "usage": _usage_dict(response_obj),
            "startTime": _iso(start_time),
            "endTime": _iso(end_time),
        }
        await self._send(payload)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        exception = kwargs.get("exception")
        payload = {
            "model": kwargs.get("model"),
            "messages": kwargs.get("messages"),
            "usage": {},
            "startTime": _iso(start_time),
            "endTime": _iso(end_time),
            "exception": str(exception) if exception else "unbekannter Fehler",
        }
        await self._send(payload)


proxy_handler_instance = MetricsWebhookLogger()
