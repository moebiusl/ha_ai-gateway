# AI Gateway

Kostenloser, kaskadierender Assist-Ersatz: erst Gemini/Groq/OpenRouter-Freikontingente, bei Ausfall oder Kontingent-Ende automatisch das nächste, zuletzt ein lokales Ollama-Modell. Ein [LiteLLM](https://docs.litellm.ai/)-Proxy mit OpenAI-kompatiblem Endpunkt, verpackt als Home-Assistant-Add-on.

Zusätzlich: manueller Hart-Wechsel zwischen den Providern live per HA-Dropdown, sowie optional ein [Grafana-Dashboard](metrics/README.md) mit Anfragen, Tokens pro Modell, Antwortzeit und den vollen Gesprächsinhalten.

## Installation

1. Dieses Repository nach GitHub pushen.
2. In Home Assistant zu **Einstellungen → Add-ons → Add-on Store** gehen.
3. Oben rechts **Repositories** öffnen, die Repository-URL hinzufügen (siehe `repository.yaml` — `url` dort mit dem tatsächlichen GitHub-Pfad ersetzen, sobald das Repo gepusht ist).
4. Store neu laden, **AI Gateway** installieren und starten.
5. Unter **Konfiguration** mindestens einen Provider eintragen (Cloud-API-Key oder eine erreichbare Ollama-Adresse).

Das Add-on liefert nur das "Gehirn" für Assist — für die vollständige Einrichtung (Ollama-Add-on, HACS-Komponente, Assist-Pipeline) siehe [DOCS.md](DOCS.md).
