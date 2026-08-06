## 0.5.3

### Fix: 502 Bad Gateway bei komplexeren Assist-Anfragen (Tool-Calls)
- Beobachtet auf dem echten Server: einfache Anfragen ("Hallo") liefen durch, Anfragen mit Tool-Calls ("Welche Lichter sind an") endeten oft in `502 Bad Gateway` und HA meldete "Timeout running pipeline"
- Ursache: kein Provider hatte einen eigenen Timeout gesetzt, `num_retries: 1` hat bei endgültig fehlschlagenden Providern (abgelaufenes Kontingent, falsches/veraltetes Modell) unnötig Zeit verdoppelt, und `router.py` hat die ganze Kaskade pauschal nach 120s abgebrochen - bei vier Providern mit je bis zu zwei Versuchen konnte das die Kaskade locker überschreiten, bevor der eigentlich funktionierende letzte Fallback (Ollama, auf CPU spürbar langsamer bei Tool-Call-Kontext) überhaupt fertig war
- `providers.py`: neue `PROVIDER_TIMEOUTS` (Gemini/Groq 15s, OpenRouter 20s, Ollama 90s) - jetzt in `build_litellm_config.py` pro Provider als `timeout` in die LiteLLM-Config geschrieben
- `litellm_settings.num_retries` von 1 auf 0 - ein zweiter Versuch bei Quota-/Auth-/Modell-Fehlern bringt nichts und kostet nur Zeit, die Kaskaden-Redundanz kommt ohnehin über die verschiedenen Provider
- `router.py`: fester 120s-Timeout ersetzt durch `UPSTREAM_TIMEOUT`, berechnet als Summe der Timeouts aller tatsächlich konfigurierten Provider (+20s Puffer) - deckt die maximal mögliche Kaskaden-Laufzeit ab, statt sie an einer beliebigen festen Zahl zu kappen

## 0.5.2

### Fix: Postgres startete auf dem echten HA-Server nie (Permission denied)
- Dank der Diagnose aus 0.5.1 jetzt sichtbar geworden: `pg_ctl -l /data/postgres.log` schlug mit `cannot create /data/postgres.log: Permission denied` fehl — `/data` selbst gehört unter HA Supervisor `root` und ist für den `postgres`-Systemnutzer nicht beschreibbar, nur das eigens angelegte `/data/postgres` (per `chown -R`) ist es
- Postgres-Log liegt jetzt unter `$PGDATA/postgres.log` (also `/data/postgres/postgres.log`) statt direkt unter `/data` — dieser Pfad ist bereits `postgres`-beschrieben
- Lokal verifiziert mit denselben Berechtigungen wie unter HA Supervisor (`/data` `root:root 755`, `/data/postgres` `postgres:postgres 700`): Postgres startet jetzt sauber durch

## 0.5.1

### Fix: Postgres-Startfehler waren unsichtbar
- `pg_ctl` schreibt Postgres' eigenes Log nach `/data/postgres.log` — das steht nicht im normalen Add-on-Protokoll, ein fehlgeschlagener Start sah dadurch nur wie "Connection refused" ohne jede Ursache aus
- `run.sh` gibt jetzt bei jedem Fehlschlag den echten Grund direkt im Add-on-Log aus: `initdb`-Fehler, `pg_ctl`-Exitcode samt `/data/postgres.log`-Inhalt, sowie das Log erneut, falls Postgres nach 30s nicht bereit ist
- Rollen-/Datenbank-Anlage und die Erfolgsmeldung "Postgres laeuft" laufen jetzt nur noch, wenn Postgres wirklich erreichbar ist, statt unbedingt zu versuchen weiterzumachen
- Lokal verifiziert: sowohl der Erfolgsfall (sauberer Start) als auch ein erzwungener Fehlerfall (korruptes Datenverzeichnis) wurden getestet — im Fehlerfall erscheint jetzt z. B. `postgres: could not access the server configuration file "/data/postgres/postgresql.conf": No such file or directory` statt nur eines stillen Timeouts

## 0.5.0

### Postgres + Grafana jetzt im selben Add-on-Container statt separater Add-ons
- Auf Wunsch: nur noch **ein** Add-on zu installieren statt drei (AI Gateway + Postgres-Add-on + Grafana-Add-on)
- Postgres läuft intern (nur `127.0.0.1:5432`, kein Port nach außen), Datenverzeichnis unter `/data/postgres` (übersteht Add-on-Updates, da `/data` der persistente Add-on-Speicher ist)
- Grafana läuft mit auf Port 3001 nach außen (bewusst **kein** HA-Ingress — bekannte Subpath-Probleme selbst beim dedizierten Community-Add-on, stattdessen direkter Port wie beim Wallpanel-Add-on, über VPN genauso erreichbar)
- Datenquelle + Dashboard sind jetzt fest ins Image einprovisioniert (`grafana/provisioning/`) statt manuellem Import — kein Rätselraten mehr über Mount-Pfade eines fremden Add-ons
- **Breaking**: Add-on-Option `metrics_db_url` entfällt, ersetzt durch `enable_metrics` (bool) + optional `grafana_admin_password`
- Neue Add-on-Option `ports: 3000/tcp: 3001` für Grafana

## 0.4.0

### Grafana läuft jetzt als HA-Add-on statt separatem docker-compose-Stack
- Grund: Zugriff auf HA läuft bei uns nur per VPN — ein separater Docker-Host für `metrics/` wäre darüber nicht ohne Weiteres erreichbar gewesen
- `metrics/` (eigenes Postgres-Image, eigener Receiver-Container, eigene Grafana-Provisionierung) entfällt komplett
- Stattdessen: bestehende Community-Add-ons installieren — [expaso/hassos-addons](https://github.com/expaso/hassos-addons) (Postgres) und [hassio-addons/addon-grafana](https://github.com/hassio-addons/addon-grafana) (Grafana, Ingress-fähig, dadurch direkt in der HA-Seitenleiste erreichbar — über denselben VPN-Zugang wie HA selbst)
- Der Log-Receiver ist jetzt Teil von `router.py` (neue Route `/internal/metrics-log`, nur lokal erreichbar) statt eines eigenen Containers — legt die benötigte Tabelle beim Start auch selbst an, kein `init.sql`-Mounting mehr nötig
- **Breaking**: Add-on-Option `metrics_webhook_url` entfällt ersatzlos, übrig bleibt nur `metrics_db_url`
- Dashboard-JSON bleibt im Repo unter `grafana/ai-gateway-overview.json`, wird jetzt einmalig manuell in Grafana importiert statt automatisch provisioniert (zuverlässiger, da der genaue Mount-Pfad im Community-Add-on nicht von hier aus verifizierbar war)

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
