import json
import os
import sys

import yaml

OPTIONS_PATH = "/data/options.json"
OUTPUT_PATH = "/tmp/litellm-config.yaml"


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

    gemini_key = clean(options.get("gemini_api_key"))
    groq_key = clean(options.get("groq_api_key"))
    openrouter_key = clean(options.get("openrouter_api_key"))
    ollama_url = clean(options.get("ollama_url"))
    master_key = clean(options.get("gateway_master_key"))

    model_gemini = clean(options.get("model_gemini")) or "gemini-2.0-flash"
    model_groq = clean(options.get("model_groq")) or "llama-3.3-70b-versatile"
    model_openrouter = clean(options.get("model_openrouter")) or "meta-llama/llama-3.3-70b-instruct:free"
    model_ollama = clean(options.get("model_ollama")) or "qwen2.5:7b"

    model_list = []
    fallback_chain = []

    # Reihenfolge = Prioritaet: zuerst kostenlose Cloud-Kontingente, zuletzt lokales Ollama.
    if gemini_key:
        model_list.append({
            "model_name": "assistant",
            "litellm_params": {"model": f"gemini/{model_gemini}", "api_key": gemini_key},
        })

    if groq_key:
        model_list.append({
            "model_name": "assistant-groq",
            "litellm_params": {"model": f"groq/{model_groq}", "api_key": groq_key},
        })
        fallback_chain.append("assistant-groq")

    if openrouter_key:
        model_list.append({
            "model_name": "assistant-openrouter",
            "litellm_params": {"model": f"openrouter/{model_openrouter}", "api_key": openrouter_key},
        })
        fallback_chain.append("assistant-openrouter")

    if ollama_url:
        model_list.append({
            "model_name": "assistant-local",
            "litellm_params": {"model": f"ollama/{model_ollama}", "api_base": ollama_url},
        })
        fallback_chain.append("assistant-local")

    if not model_list:
        print(
            "Kein Provider konfiguriert (weder Gemini/Groq/OpenRouter-Key noch ollama_url gesetzt). "
            "Bitte mindestens einen Provider in den Add-on-Optionen eintragen.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Wenn Gemini als Primaer-Modell fehlt, wird das erste verfuegbare Fallback-Modell primaer.
    if not gemini_key and fallback_chain:
        model_list[0]["model_name"] = "assistant"
        fallback_chain = fallback_chain[1:]

    litellm_settings = {
        "num_retries": 1,
        "cooldown_time": 60,
        "allowed_fails": 1,
    }
    if fallback_chain:
        litellm_settings["fallbacks"] = [{"assistant": fallback_chain}]
        litellm_settings["default_fallbacks"] = [fallback_chain[-1]]

    config = {
        "model_list": model_list,
        "litellm_settings": litellm_settings,
    }
    if master_key:
        config["general_settings"] = {"master_key": master_key}

    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)

    active_providers = [entry["model_name"] for entry in model_list]
    print(f"LiteLLM-Konfiguration geschrieben nach {OUTPUT_PATH}. Provider: {', '.join(active_providers)}")


if __name__ == "__main__":
    main()
