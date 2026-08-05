import json
import os
import time
from datetime import datetime

import httpx
import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from providers import AUTO_LABEL, configured_providers, label_to_provider_key, model_name_for

LITELLM_INTERNAL_PORT = os.environ.get("LITELLM_INTERNAL_PORT", "4001")
LITELLM_BASE_URL = f"http://127.0.0.1:{LITELLM_INTERNAL_PORT}"
ROUTER_PORT = int(os.environ.get("PORT", "4000"))
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
OVERRIDE_POLL_SECONDS = 10

METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider TEXT NOT NULL,
    trigger TEXT,
    messages JSONB,
    response TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT true,
    error TEXT
);
CREATE INDEX IF NOT EXISTS requests_ts_idx ON requests (ts DESC);
CREATE INDEX IF NOT EXISTS requests_provider_idx ON requests (provider);
"""

OPTIONS_PATH = "/data/options.json"


def read_options():
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


OPTIONS = read_options()
AVAILABLE_PROVIDERS = configured_providers(OPTIONS)
OVERRIDE_ENTITY_ID = str(OPTIONS.get("provider_override_entity_id") or "").strip() or "input_select.ai_gateway_provider_override"
METRICS_DB_URL = str(OPTIONS.get("metrics_db_url") or "").strip()

app = FastAPI()


def ensure_metrics_schema():
    """Legt die requests-Tabelle an, falls metrics_db_url gesetzt ist. Laeuft
    beim Start; ein nicht erreichbares/falsch konfiguriertes Postgres darf das
    Add-on nicht zum Absturz bringen - Metrics sind immer optional."""
    if not METRICS_DB_URL:
        return
    try:
        connection = psycopg2.connect(METRICS_DB_URL, connect_timeout=10)
        try:
            with connection.cursor() as cursor:
                cursor.execute(METRICS_SCHEMA)
            connection.commit()
        finally:
            connection.close()
        print("Metrics-Schema geprueft/angelegt.", flush=True)
    except Exception as error:  # noqa: BLE001
        print(f"Konnte Metrics-Schema nicht anlegen (metrics_db_url pruefen): {error}", flush=True)


ensure_metrics_schema()

_override_cache = {"label": AUTO_LABEL, "checked_at": 0.0}


def current_override_label():
    """Gecachter Blick auf den input_select-Helper. Fehlt SUPERVISOR_TOKEN oder
    ist der Helfer nicht (mehr) vorhanden, bleibt es beim zuletzt bekannten Wert
    (Default: Automatisch)."""
    now = time.time()
    if now - _override_cache["checked_at"] < OVERRIDE_POLL_SECONDS:
        return _override_cache["label"]
    _override_cache["checked_at"] = now

    if not SUPERVISOR_TOKEN:
        return _override_cache["label"]

    try:
        response = httpx.get(
            f"http://supervisor/core/api/states/{OVERRIDE_ENTITY_ID}",
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=5,
        )
        if response.status_code == 200:
            state = response.json().get("state")
            if state and state not in ("unavailable", "unknown"):
                _override_cache["label"] = state
    except Exception:  # noqa: BLE001 - Netzwerkfehler duerfen den Proxy nicht blockieren
        pass

    return _override_cache["label"]


def resolve_target():
    """Liefert (model_name, hard_override) fuer die aktuelle Anfrage."""
    if not AVAILABLE_PROVIDERS:
        return None, False

    label = current_override_label()
    provider_key = label_to_provider_key(label)
    if provider_key and provider_key in AVAILABLE_PROVIDERS:
        return model_name_for(provider_key), True

    return model_name_for(AVAILABLE_PROVIDERS[0]), False


def normalize_tools(body):
    """Extended OpenAI Conversation schickt Tool-Definitionen teils ohne das
    Feld "type" auf oberster Ebene. Gemini/OpenAI tolerieren das, Groqs
    Validierung ist strenger und lehnt die Anfrage komplett ab
    ('tools.0.type' : property 'type' is missing). Fehlendes "type" ist in
    der OpenAI-Tool-Spec ohnehin immer "function" - hier defensiv ergaenzen,
    statt sich auf die Kulanz des jeweiligen Providers zu verlassen."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return
    for tool in tools:
        if isinstance(tool, dict) and "type" not in tool:
            tool["type"] = "function"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    model_name, hard_override = resolve_target()
    if model_name is None:
        return JSONResponse(status_code=503, content={"error": "Kein Provider im AI Gateway konfiguriert."})

    body = await request.json()
    body["model"] = model_name
    normalize_tools(body)
    if hard_override:
        # Harter Wechsel: bewusst kein automatisches Weiterreichen an den
        # naechsten Provider in der Kaskade, auch wenn der gewaehlte Provider
        # selbst der Kaskaden-Primaerprovider waere.
        body["disable_fallbacks"] = True

    forward_headers = {"content-type": "application/json"}
    auth = request.headers.get("authorization")
    if auth:
        forward_headers["authorization"] = auth

    if body.get("stream"):
        return await proxy_streaming_response(
            f"{LITELLM_BASE_URL}/v1/chat/completions", body, forward_headers
        )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            upstream = await client.post(
                f"{LITELLM_BASE_URL}/v1/chat/completions",
                content=json.dumps(body),
                headers=forward_headers,
            )
    except httpx.HTTPError as error:
        return JSONResponse(status_code=502, content={"error": f"LiteLLM nicht erreichbar: {error}"})

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


async def proxy_streaming_response(url, body, headers):
    """Echtes Streaming-Passthrough fuer stream:true-Anfragen (SSE). Der
    Status-Code steht schon nach den Response-Headern fest, bevor der Body
    ausgelesen wird - deshalb der Umweg ueber manuelles __aenter__/__aexit__
    statt eines einfachen `async with`, das den ganzen Body puffern wuerde."""
    client = httpx.AsyncClient(timeout=120)
    stream_cm = client.stream("POST", url, content=json.dumps(body), headers=headers)
    try:
        upstream = await stream_cm.__aenter__()
    except httpx.HTTPError as error:
        await client.aclose()
        return JSONResponse(status_code=502, content={"error": f"LiteLLM nicht erreichbar: {error}"})

    status_code = upstream.status_code
    media_type = upstream.headers.get("content-type", "text/event-stream")

    async def body_iterator():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(body_iterator(), status_code=status_code, media_type=media_type)


@app.get("/v1/models")
async def list_models(request: Request):
    forward_headers = {}
    auth = request.headers.get("authorization")
    if auth:
        forward_headers["authorization"] = auth
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            upstream = await client.get(f"{LITELLM_BASE_URL}/v1/models", headers=forward_headers)
    except httpx.HTTPError as error:
        return JSONResponse(status_code=502, content={"error": f"LiteLLM nicht erreichbar: {error}"})
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


def extract_trigger(messages):
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else str(content)
    return None


def extract_response_text(response):
    if response is None:
        return None
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message") or {}
                if isinstance(message, dict) and message.get("content"):
                    return message["content"]
                if first.get("text"):
                    return first["text"]
    return str(response)


def parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_latency_ms(payload):
    start = parse_timestamp(payload.get("startTime") or payload.get("start_time"))
    end = parse_timestamp(payload.get("endTime") or payload.get("end_time"))
    if start and end:
        return max(0, int((end - start).total_seconds() * 1000))
    duration = payload.get("response_time") or payload.get("duration_ms")
    if isinstance(duration, (int, float)):
        return int(duration)
    return None


def is_failure(payload):
    if payload.get("exception") or payload.get("error"):
        return True
    status = payload.get("status") or (payload.get("metadata") or {}).get("status")
    if isinstance(status, str) and "fail" in status.lower():
        return True
    event_type = payload.get("event_type") or payload.get("call_type")
    if isinstance(event_type, str) and "fail" in event_type.lower():
        return True
    return False


@app.post("/internal/metrics-log")
async def metrics_log(request: Request):
    """Empfaengt die Payload von custom_callback.py und schreibt eine Zeile
    in die metrics_db_url-Postgres. Nur lokal erreichbar (127.0.0.1), kein
    Auth noetig - laeuft im selben Container wie der Aufrufer."""
    if not METRICS_DB_URL:
        return JSONResponse(status_code=204, content=None)

    payload = await request.json()

    usage = payload.get("usage") or {}
    tokens_in = usage.get("prompt_tokens") or usage.get("promptTokens") or 0
    tokens_out = usage.get("completion_tokens") or usage.get("completionTokens") or 0

    failure = is_failure(payload)
    error_message = None
    if failure:
        error_message = str(payload.get("exception") or payload.get("error") or "unbekannter Fehler")

    row = (
        payload.get("model") or "unbekannt",
        extract_trigger(payload.get("messages")),
        psycopg2.extras.Json(payload.get("messages")) if payload.get("messages") is not None else None,
        extract_response_text(payload.get("response")),
        int(tokens_in) if tokens_in else 0,
        int(tokens_out) if tokens_out else 0,
        compute_latency_ms(payload),
        not failure,
        error_message,
    )

    try:
        connection = psycopg2.connect(METRICS_DB_URL, connect_timeout=10)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO requests (provider, trigger, messages, response, tokens_in, tokens_out, latency_ms, success, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    row,
                )
            connection.commit()
        finally:
            connection.close()
    except Exception as error:  # noqa: BLE001 - Logging darf den eigentlichen Request nicht stoeren
        return JSONResponse(status_code=502, content={"ok": False, "error": str(error)})

    return {"ok": True}


@app.get("/health")
async def health(request: Request):
    forward_headers = {}
    auth = request.headers.get("authorization")
    if auth:
        forward_headers["authorization"] = auth
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            upstream = await client.get(f"{LITELLM_BASE_URL}/health", headers=forward_headers)
    except httpx.HTTPError as error:
        return JSONResponse(status_code=502, content={"error": f"LiteLLM nicht erreichbar: {error}"})
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=ROUTER_PORT)
