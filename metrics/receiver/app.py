import os
from datetime import datetime

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request

DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI()


def get_connection():
    return psycopg2.connect(DATABASE_URL)


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


@app.post("/log")
async def log_request(request: Request):
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

    connection = get_connection()
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

    return {"ok": True}


@app.get("/health")
async def health():
    try:
        connection = get_connection()
        connection.close()
        return {"ok": True}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)}
