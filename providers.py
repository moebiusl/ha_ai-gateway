"""Gemeinsame Provider-Logik, von build_litellm_config.py und router.py genutzt.

Feste Provider-Reihenfolge = Prioritaet der automatischen Kaskade: zuerst die
kostenlosen Cloud-Kontingente, zuletzt das lokale Ollama-Modell.
"""

PROVIDER_ORDER = ["gemini", "groq", "openrouter", "ollama"]

PROVIDER_LABELS = {
    "gemini": "Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "ollama": "Ollama (lokal)",
}

AUTO_LABEL = "Automatisch (Kaskade)"

# Cloud-Provider sollen bei Problemen (Quota, falsches Modell, Netzwerk)
# schnell auf den naechsten in der Kaskade weiterreichen statt lange zu haengen.
# Ollama laeuft typischerweise lokal auf der CPU ohne GPU - eine Tool-Call-
# Anfrage mit vollem HA-Entity-Kontext braucht dort spuerbar laenger, deshalb
# bekommt es als letztes Glied der Kaskade deutlich mehr Zeit.
PROVIDER_TIMEOUTS = {
    "gemini": 15,
    "groq": 15,
    "openrouter": 20,
    "ollama": 90,
}


def model_name_for(provider_key):
    return f"provider-{provider_key}"


def label_to_provider_key(label):
    for key, value in PROVIDER_LABELS.items():
        if value == label:
            return key
    return None


def is_provider_configured(provider_key, options):
    if provider_key == "gemini":
        return bool(str(options.get("gemini_api_key") or "").strip())
    if provider_key == "groq":
        return bool(str(options.get("groq_api_key") or "").strip())
    if provider_key == "openrouter":
        return bool(str(options.get("openrouter_api_key") or "").strip())
    if provider_key == "ollama":
        return bool(str(options.get("ollama_url") or "").strip())
    return False


def configured_providers(options):
    """Liste der konfigurierten Provider-Keys, in Prioritaetsreihenfolge."""
    return [key for key in PROVIDER_ORDER if is_provider_configured(key, options)]
