## 0.3.1

### Fix: Groq lehnte Tool-Calls ab
- Extended OpenAI Conversation schickt Tool-Definitionen teils ohne das Feld `type` auf oberster Ebene — Gemini toleriert das, Groq nicht (`'tools.0.type' : property 'type' is missing`, 400 Bad Request)
- `router.py` ergänzt jetzt defensiv `"type": "function"`, wenn es fehlt, bevor die Anfrage weitergereicht wird
- Gefunden beim ersten echten Deployment: zusätzlich lagen ein falsch eingetragener `ollama_url`-Wert (Beispiel-Hostname statt der echten Add-on-Adresse) und ein Gemini-Konto ohne Gratis-Kontingent vor — beides nutzerseitige Konfiguration, kein Code-Fix nötig

## 0.3.0

### Offene Punkte geschlossen
- `router.py` unterstützt jetzt echtes Streaming-Passthrough (`stream: true`) für den Fall, dass Extended OpenAI Conversation Antworten gestreamt anfragt — vorher wurde nur Request/Response ohne Streaming weitergereicht
- `repository.yaml` auf die tatsächliche Repo-URL gesetzt (`github.com/moebiusl/ai-gateway`)
- README.md überarbeitet: Architekturübersicht, Voraussetzungen, vollständige Installationsanleitung
- CHANGELOG.md eingeführt

## 0.2.0

### Manueller Provider-Wechsel
- Neue Komponente `router.py` vor LiteLLM: liest einen HA-`input_select`-Helfer (`provider_override_entity_id`) und erzwingt bei Bedarf einen bestimmten Provider ohne automatischen Fallback
- Provider-Namen in der generierten LiteLLM-Config sind jetzt fest (`provider-gemini`, `provider-groq`, `provider-openrouter`, `provider-ollama`) statt dynamisch umbenannt — Voraussetzung für einen eindeutigen Override

### Grafana-Observability
- Neuer eigenständiger docker-compose-Stack `metrics/` (Postgres + Log-Receiver + Grafana), unabhängig von bestehender Monitoring-Infrastruktur
- Vorprovisioniertes Dashboard: Anfragen über Zeit, Tokens pro Modell, Ø-Antwortzeit, Fehlerquote, Tabelle mit vollem Prompt/Antwort je Anfrage
- `custom_callback.py`: eigener LiteLLM-`CustomLogger`, da der eingebaute `generic_api`-Callback beim Testen als LiteLLM-Enterprise-Funktion (Lizenzpflicht) entlarvt wurde — kostenloser Ersatz mit identischem Datenumfang
- `status_push.py` erweitert: zusätzliche HA-Sensoren für Anfragen/Tokens/Ø-Antwortzeit des laufenden Tages (aus der `metrics`-Postgres), plus `override`-Attribut am bestehenden Status-Sensor

## 0.1.0

### Erste Version
- LiteLLM-Proxy als Home-Assistant-Add-on, kaskadierender Fallback Gemini → Groq → OpenRouter → Ollama, jeder Provider optional
- `status_push.py`: Live-Status (aktiver/ausgefallener Provider) als HA-Sensor
- Getrennt von `ha-wallpannel` als eigenes Repository/Add-on
