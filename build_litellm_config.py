import json
import os
import sys

import yaml

from providers import PROVIDER_ORDER, PROVIDER_TIMEOUTS, configured_providers, model_name_for

OPTIONS_PATH = "/data/options.json"
# custom_callback.py muss laut LiteLLM-Doku im selben Verzeichnis wie die
# config.yaml liegen -> beide in /app statt /tmp.
OUTPUT_PATH = "/app/litellm-config.yaml"

MODEL_SPEC = {
    "gemini": lambda options: (
        f"gemini/{clean(options.get('model_gemini')) or 'gemini-2.0-flash'}",
        {"api_key": clean(options.get("gemini_api_key"))},
    ),
    "groq": lambda options: (
        f"groq/{clean(options.get('model_groq')) or 'llama-3.3-70b-versatile'}",
        {"api_key": clean(options.get("groq_api_key"))},
    ),
    "openrouter": lambda options: (
        f"openrouter/{clean(options.get('model_openrouter')) or 'openai/gpt-oss-20b:free'}",
        {"api_key": clean(options.get("openrouter_api_key"))},
    ),
    "ollama": lambda options: (
        f"ollama/{clean(options.get('model_ollama')) or 'qwen2.5:7b'}",
        {"api_base": clean(options.get("ollama_url"))},
    ),
}


def read_options():
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def main():
    options = read_options()
    master_key = clean(options.get("gateway_master_key"))
    metrics_enabled = bool(options.get("enable_metrics"))

    available = configured_providers(options)
    if not available:
        print(
            "Kein Provider konfiguriert (weder Gemini/Groq/OpenRouter-Key noch ollama_url gesetzt). "
            "Bitte mindestens einen Provider in den Add-on-Optionen eintragen.",
            file=sys.stderr,
        )
        sys.exit(1)

    model_list = []
    for key in available:
        model_spec, extra_params = MODEL_SPEC[key](options)
        extra_params.setdefault("timeout", PROVIDER_TIMEOUTS.get(key, 30))
        model_list.append({
            "model_name": model_name_for(key),
            "litellm_params": {"model": model_spec, **extra_params},
        })

    # Automatik-Kaskade: der erste konfigurierte Provider faellt bei Fehler auf
    # die naechsten (in PROVIDER_ORDER) konfigurierten zurueck.
    fallback_chain = [model_name_for(key) for key in available[1:]]

    litellm_settings = {
        # num_retries=0: bei Quota-/Modell-/Auth-Fehlern (429, 404, ...) hilft
        # ein Retry auf demselben Provider ohnehin nicht - das kostet nur
        # Zeit, die dem naechsten Fallback-Kandidaten (am Ende Ollama) fehlt.
        "num_retries": 0,
        "cooldown_time": 60,
        "allowed_fails": 1,
    }
    if fallback_chain:
        primary_name = model_name_for(available[0])
        litellm_settings["fallbacks"] = [{primary_name: fallback_chain}]
        litellm_settings["default_fallbacks"] = [fallback_chain[-1]]

    if metrics_enabled:
        # Eigener CustomLogger statt des eingebauten "generic_api"-Callbacks -
        # letzterer ist eine LiteLLM-Enterprise-Funktion (Lizenzpflicht), das
        # ist beim Testen aufgefallen. custom_callback.py postet lokal an
        # router.py, das dann in die mitgelieferte Postgres schreibt.
        litellm_settings["callbacks"] = "custom_callback.proxy_handler_instance"

    config = {
        "model_list": model_list,
        "litellm_settings": litellm_settings,
    }
    if master_key:
        config["general_settings"] = {"master_key": master_key}

    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)

    # run.sh muss vor dem Start von Postgres/Grafana wissen, ob enable_metrics
    # gesetzt ist - os.environ hier zu setzen bringt nichts, das gilt nur fuer
    # diesen kurzlebigen Python-Kindprozess, deshalb der Umweg ueber eine Datei.
    with open("/tmp/gateway-env.sh", "w", encoding="utf-8") as handle:
        handle.write(f"export ENABLE_METRICS={'true' if metrics_enabled else 'false'}\n")

    print(f"LiteLLM-Konfiguration geschrieben nach {OUTPUT_PATH}. Provider: {', '.join(available)}")


if __name__ == "__main__":
    main()
