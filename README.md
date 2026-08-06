# AI Gateway

Kostenloser, kaskadierender Ersatz für den Home-Assistant-Assist-Conversation-Agent: erst kostenlose Cloud-Kontingente (Gemini, Groq, OpenRouter), bei Fehler oder Kontingent-Ende automatisch das nächste, ganz am Ende ein lokales Ollama-Modell als garantiert verfügbarer Fallback. Technisch ein [LiteLLM](https://docs.litellm.ai/)-Proxy mit OpenAI-kompatiblem Endpunkt, verpackt als Home-Assistant-Add-on.

Zusätzlich:
- **Manueller Hart-Wechsel** zwischen den Providern, live per HA-Dropdown umschaltbar — ohne Neustart, ohne automatischen Fallback, wenn du bewusst einen bestimmten Provider erzwingen willst.
- **Grafana-Dashboard** (optional, per `enable_metrics: true` — Postgres und Grafana laufen direkt im selben Add-on-Container mit, nichts weiter zu installieren): Anfragen über Zeit, Tokens pro Modell, Antwortzeit, Fehlerquote, sowie eine Tabelle mit jeder Anfrage inklusive auslösendem Prompt und voller Antwort.
- Ein paar Kennzahlen zusätzlich als **HA-Entitäten**, die sich auf jedem HA-Dashboard anzeigen lassen.

## Architektur

```
Assist-Pipeline (HA)
  └─ Extended OpenAI Conversation (HACS-Komponente, separat zu installieren)
       └─ AI-Gateway-Add-on (ein Container, ein Add-on)
            ├─ router.py       (Port 4000, nach außen) — wertet Override-Helper aus, leitet weiter,
            │                    schreibt optional Anfrage-Metriken nach Postgres
            ├─ LiteLLM-Proxy   (Port 4001, nur intern)  — Kaskade Gemini → Groq → OpenRouter → Ollama
            ├─ custom_callback.py — meldet jede Anfrage optional lokal an router.py
            ├─ status_push.py  — pusht aktiven Provider + Kennzahlen als HA-Sensoren
            ├─ Postgres (nur 127.0.0.1, optional per enable_metrics)
            └─ Grafana  (Port 3001, nach außen, optional per enable_metrics) — vorprovisioniertes Dashboard
  └─ separates Ollama-Add-on (bestehendes Community-Add-on, nicht Teil dieses Repos)
```

Läuft komplett als ein Home-Assistant-Add-on auf derselben Box — kein separater Docker-Host nötig, über denselben Zugang (z. B. VPN zu HA) erreichbar wie HA selbst.

## Voraussetzungen

- Eine Home-Assistant-Instanz mit Supervisor (HA OS oder Supervised) für das Add-on selbst
- Mindestens ein kostenloser API-Key (Gemini und/oder Groq und/oder OpenRouter) **oder** ein erreichbares Ollama — mindestens einer von beiden ist Pflicht
- [HACS](https://hacs.xyz/) + die Community-Komponente `jekalmin/extended_openai_conversation` (die offizielle HA-OpenAI-Integration unterstützt keine eigene Base-URL)

## Installation

1. Dieses Repository nach GitHub pushen (`github.com/moebiusl/ai-gateway`, siehe `repository.yaml`).
2. In Home Assistant zu **Einstellungen → Add-ons → Add-on Store** gehen.
3. Oben rechts **Repositories** öffnen, `https://github.com/moebiusl/ai-gateway` hinzufügen.
4. Store neu laden, **AI Gateway** installieren und starten.
5. Unter **Konfiguration** mindestens einen Provider eintragen (Cloud-API-Key oder eine erreichbare Ollama-Adresse).

Das Add-on liefert nur das "Gehirn" für Assist — für die vollständige Einrichtung (Ollama-Add-on, HACS-Komponente, Override-Helfer, Assist-Pipeline, Grafana) siehe **[DOCS.md](DOCS.md)**.

## Versionierung

Siehe [CHANGELOG.md](CHANGELOG.md). Die Add-on-Version steht in `config.yaml` (`version:`) und wird bei jeder funktionalen Änderung hochgezählt.
