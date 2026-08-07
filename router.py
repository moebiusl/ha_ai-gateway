import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime

import httpx
import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from providers import (
    AUTO_LABEL,
    PROVIDER_TIMEOUTS,
    configured_providers,
    label_to_provider_key,
    model_name_for,
    raw_model_to_provider_map,
)

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
# Postgres laeuft im selben Container, nur intern erreichbar (127.0.0.1,
# kein Port nach aussen) - deshalb feste Zugangsdaten statt Nutzereingabe.
INTERNAL_METRICS_DB_URL = "postgresql://ai_gateway:ai-gateway-internal@127.0.0.1:5432/ai_gateway"


def read_options():
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


OPTIONS = read_options()
AVAILABLE_PROVIDERS = configured_providers(OPTIONS)
RAW_MODEL_TO_PROVIDER = raw_model_to_provider_map(OPTIONS)
OVERRIDE_ENTITY_ID = str(OPTIONS.get("provider_override_entity_id") or "").strip() or "input_select.ai_gateway_provider_override"
METRICS_DB_URL = INTERNAL_METRICS_DB_URL if OPTIONS.get("enable_metrics") else ""
RESPONSE_CACHE_SECONDS = int(OPTIONS.get("response_cache_seconds") or 0)

# Muss die gesamte moegliche Kaskaden-Laufzeit abdecken (Summe der
# Provider-Timeouts aus providers.py, jeder Provider wird mit num_retries=0
# hoechstens einmal versucht) - sonst kappt der Router die Anfrage, bevor
# LiteLLM ueberhaupt beim letzten Fallback (typischerweise Ollama) angekommen
# ist, obwohl der am Ende noch erfolgreich geantwortet haette.
UPSTREAM_TIMEOUT = max(60, sum(PROVIDER_TIMEOUTS.get(p, 30) for p in AVAILABLE_PROVIDERS) + 20)

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


_provider_cooldown_until = {}

# Reihenfolge wichtig: zuerst der eindeutigste/spezifischste Fall.
# OpenRouter liefert den Tages-Reset als Unix-Millisekunden im
# "X-RateLimit-Reset"-Header (im Fehlertext eingebettetes JSON), Groq nur
# eine relative "try again in ...s"-Angabe.
RATE_LIMIT_RESET_MS_RE = re.compile(r'"X-RateLimit-Reset"\s*:\s*"?(\d{10,})"?')
RETRY_AFTER_SECONDS_RE = re.compile(r'"retry_after_seconds"\s*:\s*(\d+)')
TRY_AGAIN_RE = re.compile(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def parse_retry_after_seconds(error_text):
    """Extrahiert aus den Fehlermeldungen von Groq/OpenRouter eine
    Wartezeit, um deren Kontingent proaktiv als 'gerade erschoepft' zu
    markieren - auf dem echten Server hat das Gateway sonst bei jeder
    einzelnen Folgeanfrage erneut die vollen ~35s auf zwei bereits bekannt
    tote Provider gewartet, bevor es bei Ollama ankam. Liefert None, wenn
    keines der bekannten Muster passt - dann bleibt der Provider einfach
    unveraendert im normalen Kaskaden-Ablauf, es wird nichts geraten."""
    if not error_text:
        return None

    match = RATE_LIMIT_RESET_MS_RE.search(error_text)
    if match:
        return max(0.0, int(match.group(1)) / 1000 - time.time())

    match = RETRY_AFTER_SECONDS_RE.search(error_text)
    if match:
        return float(match.group(1))

    match = TRY_AGAIN_RE.search(error_text)
    if match:
        minutes = int(match.group(1) or 0)
        seconds = float(match.group(2))
        return minutes * 60 + seconds

    return None


def mark_provider_cooldown(raw_model, error_text):
    provider_key = RAW_MODEL_TO_PROVIDER.get(raw_model)
    if not provider_key:
        return
    delay = parse_retry_after_seconds(error_text)
    if delay is None:
        return
    until = time.time() + delay
    _provider_cooldown_until[provider_key] = until
    print(
        f"Provider '{provider_key}' als erschoepft markiert bis "
        f"{time.strftime('%H:%M:%S', time.localtime(until))} (Grund: {str(error_text)[:150]})",
        flush=True,
    )


def clear_provider_cooldown(raw_model):
    provider_key = RAW_MODEL_TO_PROVIDER.get(raw_model)
    if provider_key:
        _provider_cooldown_until.pop(provider_key, None)


def provider_in_cooldown(provider_key):
    until = _provider_cooldown_until.get(provider_key)
    return until is not None and time.time() < until


def resolve_target():
    """Liefert (model_name, hard_override) fuer die aktuelle Anfrage."""
    if not AVAILABLE_PROVIDERS:
        return None, False

    label = current_override_label()
    provider_key = label_to_provider_key(label)
    if provider_key and provider_key in AVAILABLE_PROVIDERS:
        return model_name_for(provider_key), True

    for candidate in AVAILABLE_PROVIDERS:
        if not provider_in_cooldown(candidate):
            if candidate != AVAILABLE_PROVIDERS[0]:
                print(f"Ueberspringe bekannt erschoepfte Provider, starte Kaskade bei '{candidate}'.", flush=True)
            return model_name_for(candidate), False

    # Alle bekannten Provider gelten als erschoepft (z.B. Reset-Zeit falsch
    # geschaetzt) - trotzdem mit dem ersten starten, damit die normale
    # Fehlerbehandlung/Kaskade greift, statt komplett zu blockieren.
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


ENTITY_TABLE_HEADER = "entity_id,name,state,aliases"
UNAVAILABLE_STATES = {"unavailable", "unknown"}
TRIM_UNAVAILABLE_ENTITIES = bool(OPTIONS.get("trim_unavailable_entities", True))

# Kamera-/Bewegungserkennungs-Helfer (z.B. aus Frigate-Blueprints) sind nie
# per Sprachbefehl relevant und stehen praktisch immer auf 'unavailable' -
# werden unabhaengig vom erkannten Thema immer ausgeschlossen, statt auf die
# Stichwort-Heuristik von filter_entities_by_topic angewiesen zu sein.
CAMERA_MOTION_MARKERS = ("motion_detected", "person_detected", "pet_detected", "camera_enabled")
EXCLUDE_CAMERA_MOTION_ENTITIES = bool(OPTIONS.get("exclude_camera_motion_entities", True))

# Extended OpenAI Conversation traegt hier manchmal ein Python-Objekt-Repr
# ein statt eines echten Alias-Namens oder eines leeren Felds - reines
# Rauschen, kostet aber Tokens in jeder betroffenen Zeile.
GARBAGE_ALIAS_VALUES = {"computednametype._singleton"}

# Grobe Stichwort-Heuristik: Anfrage-Text (lowercase) enthaelt eines der
# Woerter -> die zugeordneten Domains gelten als relevant. Mehrdeutige
# Konzepte (z.B. "Tor" = sowohl Endschalter-Sensor als auch Steuer-Switch)
# bewusst auf mehrere Domains gemappt - im Zweifel lieber eine Domain zu
# viel behalten als eine zu wenig.
DOMAIN_KEYWORDS = [
    ({"lampe", "licht", "leuchte", "beleuchtung"}, {"light"}),
    ({"steckdose", "schalter", "stecker"}, {"switch"}),
    ({"pumpe"}, {"switch", "sensor"}),
    ({"rollladen", "rolladen", "vorhang", "jalousie", "rollo"}, {"cover"}),
    ({"heizung", "thermostat", "klima"}, {"climate"}),
    ({"musik", "lautsprecher", "fernseher", "radio"}, {"media_player"}),
    ({"tür", "tuer", "fenster"}, {"binary_sensor", "cover"}),
    ({"tor"}, {"binary_sensor", "switch"}),
    ({"wetter", "temperatur", "luftfeuchtigkeit", "feuchtigkeit"}, {"sensor", "climate"}),
    ({"einkaufsliste"}, {"todo"}),
]
FILTER_ENTITIES_BY_TOPIC = bool(OPTIONS.get("filter_entities_by_topic", False))


def _split_entity_table(content):
    """Findet die von Extended OpenAI Conversation generierte CSV-
    Geraetetabelle im System-Prompt. Erkennt sie defensiv an der exakten
    Kopfzeile - findet sie sich nicht (anderes/geaendertes Prompt-Format),
    liefert die Funktion None, statt etwas Falsches zu zerschneiden.
    Returns (lines, header_idx, end_idx, body_lines, rows) oder None."""
    lines = content.split("\n")
    try:
        header_idx = lines.index(ENTITY_TABLE_HEADER)
    except ValueError:
        return None

    end_idx = None
    for i in range(header_idx + 1, len(lines)):
        if lines[i].strip() == "```":
            end_idx = i
            break
    if end_idx is None:
        return None

    body_lines = lines[header_idx + 1 : end_idx]
    try:
        rows = list(csv.reader(body_lines))
    except csv.Error:
        return None

    return lines, header_idx, end_idx, body_lines, rows


def trim_unavailable_entities(content):
    """Dauerhaft offline/kaputte Geraete (state 'unavailable'/'unknown')
    liefern nie eine brauchbare Antwort, kosten aber bei jeder einzelnen
    Anfrage volle Tokens - auf dem echten Server machten sie ueber die
    Haelfte der Geraete-Tabelle aus. Filtert sie automatisch raus, statt
    dass sie manuell aus der HA-Assist-Freigabe entfernt werden muessen -
    kommt ein Geraet wieder online, taucht es von selbst wieder auf."""
    split = _split_entity_table(content)
    if split is None:
        return content, 0
    lines, header_idx, end_idx, body_lines, rows = split

    kept_lines = []
    removed = 0
    for line, row in zip(body_lines, rows):
        if len(row) >= 3 and row[2].strip() in UNAVAILABLE_STATES:
            removed += 1
            continue
        kept_lines.append(line)

    if removed == 0:
        return content, 0

    new_lines = lines[: header_idx + 1] + kept_lines + lines[end_idx:]
    return "\n".join(new_lines), removed


def domains_for_trigger(trigger_text):
    if not trigger_text:
        return None
    lowered = trigger_text.lower()
    matched = set()
    for keywords, domains in DOMAIN_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            matched |= domains
    return matched or None


def filter_entities_by_topic(content, trigger_text):
    """Behaelt nur Entities, deren Domain (light/switch/...) zu den anhand
    von DOMAIN_KEYWORDS im Anfrage-Text erkannten Themen passt. Erkennt die
    Heuristik nichts Eindeutiges, wird NICHT gefiltert - lieber zu viel
    Kontext schicken als eine Entity zu verlieren, die fuer die Antwort
    gebraucht wird. Deshalb standardmaessig aus (filter_entities_by_topic)."""
    domains = domains_for_trigger(trigger_text)
    if not domains:
        return content, 0

    split = _split_entity_table(content)
    if split is None:
        return content, 0
    lines, header_idx, end_idx, body_lines, rows = split

    kept_lines = []
    removed = 0
    for line, row in zip(body_lines, rows):
        entity_id = row[0].strip() if row else ""
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        if domain and domain not in domains:
            removed += 1
            continue
        kept_lines.append(line)

    if removed == 0:
        return content, 0

    new_lines = lines[: header_idx + 1] + kept_lines + lines[end_idx:]
    return "\n".join(new_lines), removed


def exclude_camera_motion_entities(content):
    """Entfernt Kamera-/Bewegungserkennungs-Helfer (siehe
    CAMERA_MOTION_MARKERS) unabhaengig vom erkannten Thema - anders als
    filter_entities_by_topic ist das kein Rateergebnis, sondern eine feste
    Ausschlussliste fuer Entities, die nie per Sprachbefehl relevant sind."""
    split = _split_entity_table(content)
    if split is None:
        return content, 0
    lines, header_idx, end_idx, body_lines, rows = split

    kept_lines = []
    removed = 0
    for line, row in zip(body_lines, rows):
        entity_id = row[0].strip() if row else ""
        if any(marker in entity_id for marker in CAMERA_MOTION_MARKERS):
            removed += 1
            continue
        kept_lines.append(line)

    if removed == 0:
        return content, 0

    new_lines = lines[: header_idx + 1] + kept_lines + lines[end_idx:]
    return "\n".join(new_lines), removed


def clean_garbage_aliases(content):
    """Leert nur das bekannte Python-Objekt-Repr-Muster (siehe
    GARBAGE_ALIAS_VALUES) im aliases-Feld, ruehrt echte Alias-Werte nicht
    an."""
    split = _split_entity_table(content)
    if split is None:
        return content, 0
    lines, header_idx, end_idx, body_lines, rows = split

    new_body_lines = []
    changed = 0
    for line, row in zip(body_lines, rows):
        if len(row) >= 4 and row[3].strip().lower() in GARBAGE_ALIAS_VALUES:
            row = list(row)
            row[3] = ""
            new_body_lines.append(",".join(row))
            changed += 1
        else:
            new_body_lines.append(line)

    if changed == 0:
        return content, 0

    new_lines = lines[: header_idx + 1] + new_body_lines + lines[end_idx:]
    return "\n".join(new_lines), changed


def apply_entity_trimming(body):
    if not (TRIM_UNAVAILABLE_ENTITIES or FILTER_ENTITIES_BY_TOPIC or EXCLUDE_CAMERA_MOTION_ENTITIES):
        return
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    trigger_text = extract_trigger(messages) if FILTER_ENTITIES_BY_TOPIC else None
    for message in messages:
        if not (isinstance(message, dict) and message.get("role") == "system"):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        total_removed = 0
        aliases_cleaned = 0
        if TRIM_UNAVAILABLE_ENTITIES:
            content, removed = trim_unavailable_entities(content)
            total_removed += removed
        if EXCLUDE_CAMERA_MOTION_ENTITIES:
            content, removed = exclude_camera_motion_entities(content)
            total_removed += removed
        if FILTER_ENTITIES_BY_TOPIC:
            content, removed = filter_entities_by_topic(content, trigger_text)
            total_removed += removed
        content, aliases_cleaned = clean_garbage_aliases(content)
        if total_removed or aliases_cleaned:
            message["content"] = content
            print(
                f"{total_removed} Entities aus System-Prompt entfernt, "
                f"{aliases_cleaned} Alias-Muell-Werte bereinigt.",
                flush=True,
            )


CURRENT_TIME_LINE_RE = re.compile(r"^Current Time:.*$", re.MULTILINE)
_response_cache = {}


def response_cache_key(body):
    """Cache-Key aus Modell + Anfrage-Text + Geraete-Tabelle (nach den
    Trimming-Stufen oben), OHNE die 'Current Time: ...'-Zeile, die sich bei
    jeder Anfrage aendert, obwohl sich am relevanten Weltzustand nichts
    getan hat. Dedupliziert damit ident wiederholte Anfragen innerhalb
    RESPONSE_CACHE_SECONDS - auf dem echten Server hat z.B. ein HA-Retry
    dieselbe Frage Sekunden spaeter nochmal gestellt und dabei ein zweites
    Mal Kontingent verbraucht."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    trigger = extract_trigger(messages)
    if not trigger:
        return None
    system_content = ""
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content")
            if isinstance(content, str):
                system_content = content
            break
    normalized_system = CURRENT_TIME_LINE_RE.sub("", system_content)
    raw = f"{body.get('model')}\n{trigger}\n{normalized_system}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cached_response(cache_key):
    if not cache_key:
        return None
    entry = _response_cache.get(cache_key)
    if entry is None:
        return None
    content, status_code, media_type, expires_at = entry
    if expires_at < time.time():
        del _response_cache[cache_key]
        return None
    return content, status_code, media_type


def store_cached_response(cache_key, content, status_code, media_type):
    if not cache_key:
        return
    now = time.time()
    _response_cache[cache_key] = (content, status_code, media_type, now + RESPONSE_CACHE_SECONDS)
    # Nebenbei abgelaufene Eintraege raeumen, statt eines eigenen Timers -
    # bei der jetzt ueblichen Anfragerate bleibt das ein kleines Dict.
    expired = [key for key, (_, _, _, expires_at) in _response_cache.items() if expires_at < now]
    for key in expired:
        del _response_cache[key]


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    model_name, hard_override = resolve_target()
    if model_name is None:
        return JSONResponse(status_code=503, content={"error": "Kein Provider im AI Gateway konfiguriert."})

    body = await request.json()
    body["model"] = model_name
    normalize_tools(body)
    apply_entity_trimming(body)
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

    cache_key = response_cache_key(body) if RESPONSE_CACHE_SECONDS > 0 else None
    cached = cached_response(cache_key)
    if cached is not None:
        content, status_code, media_type = cached
        print("Cache-Treffer fuer identische Anfrage - kein Provider-Aufruf noetig.", flush=True)
        return Response(content=content, status_code=status_code, media_type=media_type)

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            upstream = await client.post(
                f"{LITELLM_BASE_URL}/v1/chat/completions",
                content=json.dumps(body),
                headers=forward_headers,
            )
    except httpx.HTTPError as error:
        return JSONResponse(status_code=502, content={"error": f"LiteLLM nicht erreichbar: {error}"})

    media_type = upstream.headers.get("content-type", "application/json")
    if cache_key and upstream.status_code == 200:
        store_cached_response(cache_key, upstream.content, upstream.status_code, media_type)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=media_type,
    )


async def proxy_streaming_response(url, body, headers):
    """Echtes Streaming-Passthrough fuer stream:true-Anfragen (SSE). Der
    Status-Code steht schon nach den Response-Headern fest, bevor der Body
    ausgelesen wird - deshalb der Umweg ueber manuelles __aenter__/__aexit__
    statt eines einfachen `async with`, das den ganzen Body puffern wuerde."""
    client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)
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
        mark_provider_cooldown(payload.get("model"), error_message)
    else:
        clear_provider_cooldown(payload.get("model"))

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
