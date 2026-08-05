# AI Gateway Metrics

Eigenständiger docker-compose-Stack (Postgres + kleiner Log-Receiver + Grafana) für die Anfragen-Historie des AI-Gateway-Add-ons: Anfragen über Zeit, Tokens pro Modell, Antwortzeit, Fehlerquote und eine Tabelle mit den letzten Anfragen inkl. auslösendem Prompt und voller Antwort.

Läuft **nicht** auf der Home-Assistant-OS-Box (die erlaubt keine freien Zusatzcontainer), sondern auf eurem normalen Docker-Host — genau wie euer bestehendes `monitoring-service`-Projekt. Unabhängig von dessen Postgres/Grafana, eigene Datenbank.

## Start

```bash
cp .env.example .env
# Passwörter in .env anpassen
docker compose up -d
```

- Grafana: `http://<docker-host>:3001` (Login aus `.env`, Standard-Dashboard "AI Gateway" ist automatisch vorhanden)
- Receiver: `http://<docker-host>:8090/log` — diese Adresse trägst du im AI-Gateway-Add-on unter `metrics_webhook_url` ein
- Postgres: `<docker-host>:5433` — diese Verbindung (als vollständige URL, z. B. `postgresql://ai_gateway:<passwort>@<docker-host>:5433/ai_gateway`) trägst du im Add-on unter `metrics_db_url` ein, damit zusätzlich ein paar Kennzahlen als HA-Entitäten erscheinen

## Voraussetzung

Der Docker-Host, auf dem dieser Stack läuft, muss von der Home-Assistant-OS-Box aus im LAN erreichbar sein (Receiver-Port fürs Logging, Postgres-Port für die HA-Sensoren).

## Daten

Es werden volle Gesprächsinhalte gespeichert (Prompt + Antwort im Klartext) — bewusst so gewünscht, um im Dashboard nachvollziehen zu können, was gefragt und geantwortet wurde. Die Postgres-Daten liegen unter `./data/postgres` (Volume), Grafana-Zustand unter `./data/grafana`.
