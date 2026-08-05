import json
import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from providers import AUTO_LABEL, configured_providers, label_to_provider_key, model_name_for

LITELLM_INTERNAL_PORT = os.environ.get("LITELLM_INTERNAL_PORT", "4001")
LITELLM_BASE_URL = f"http://127.0.0.1:{LITELLM_INTERNAL_PORT}"
ROUTER_PORT = int(os.environ.get("PORT", "4000"))
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
OVERRIDE_POLL_SECONDS = 10

OPTIONS_PATH = "/data/options.json"


def read_options():
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


OPTIONS = read_options()
AVAILABLE_PROVIDERS = configured_providers(OPTIONS)
OVERRIDE_ENTITY_ID = str(OPTIONS.get("provider_override_entity_id") or "").strip() or "input_select.ai_gateway_provider_override"

app = FastAPI()

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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    model_name, hard_override = resolve_target()
    if model_name is None:
        return JSONResponse(status_code=503, content={"error": "Kein Provider im AI Gateway konfiguriert."})

    body = await request.json()
    body["model"] = model_name
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
