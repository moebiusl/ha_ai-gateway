## 0.9.0

### Neu: mehr Dashboard-Entities - Cooldown-Status, letzte Anfrage, Gemini-Kontingent
- Recherchiert (offizielle Google-Doku geprueft): es gibt keine API oder Response-Header, um Googles echtes Gemini-Kontingent live abzufragen - nur die manuelle Ansicht in AI Studio. Bewusst KEINE Preise/Kosten in den neuen Entities (auf Wunsch), stattdessen eine reine Prozent-Schaetzung aus der eigenen geloggten Nutzung gegen ein konfigurierbares Tageslimit
- `router.py`: neuer `GET /internal/cooldown-status`-Endpoint - macht den bisher nur router-intern sichtbaren Cooldown-Zustand pro Provider fuer status_push.py (eigener Prozess) abrufbar
- `status_push.py`:
  - `sensor.ai_gateway_active_provider` bekommt ein neues Attribut `cooldowns` (welche Provider gerade uebersprungen werden und bis wann)
  - `sensor.ai_gateway_requests_today` / `sensor.ai_gateway_tokens_today` bekommen ein `by_provider`-Attribut (Aufschluesselung pro Provider)
  - neuer `sensor.ai_gateway_last_request` (Zeitpunkt, Provider, Anfrage-Text, Erfolg, Antwortzeit, Tokens)
  - neuer `sensor.ai_gateway_gemini_quota_pct` (nur wenn Gemini konfiguriert) - Prozent der heutigen Gemini-Anfragen gegen `gemini_daily_request_limit` (neue Option, Standard 10000 - eigenes Limit unter aistudio.google.com/rate-limit nachsehen)
- `DOCS.md`: Live-Status-Abschnitt komplett aktualisiert, inkl. minimalem Lovelace-Dashboard-Beispiel

## 0.8.4

### Fix: gemini-2.5-flash fuer neue Google-Cloud-Projekte gesperrt
- 0.8.3 reichte nicht: `gemini-2.5-flash` ist zwar laut allgemeiner Google-Doku noch GA gelistet, aber fuer neu angelegte Projekte/Keys gesperrt ("This model ... is no longer available to new users") - diese kontospezifische Einschraenkung taucht auf der allgemeinen Modell-Seite nicht auf, deshalb hat die Doku-Recherche aus 0.8.3 sie nicht gefunden
- Im AI-Studio-Playground verifiziert (dort werden nur tatsaechlich fuer den eigenen Account anwaehlbare Modelle gelistet, nicht alle generell existierenden): `gemini-3.6-flash` verfuegbar - `config.yaml`/`build_litellm_config.py` Standard entsprechend aktualisiert
- `DOCS.md`: Hinweis ergaenzt, bei erneuten "not available"-Fehlern direkt im AI-Studio-Playground nachzusehen statt sich auf die allgemeine Modell-Doku zu verlassen, da diese Konto-spezifische Sperren nicht zuverlaessig zeigt

## 0.8.3

### Fix: Standard-Gemini-Modell aktualisiert - gemini-2.0-flash im Juni 2026 abgeschaltet
- Beobachtet: `litellm.NotFoundError: GeminiException - ... "This model models/gemini-2.0-flash is no longer available"` - gegen die offizielle Google-Doku geprueft (nicht nur Suchergebnisse), `gemini-2.0-flash` und `gemini-2.0-flash-lite` wurden am 1. Juni 2026 komplett abgeschaltet
- `config.yaml`/`build_litellm_config.py`: Standard auf `gemini-2.5-flash` aktualisiert (aktuell GA, volle Flash-Faehigkeiten, am naechsten am bisherigen Default) - bestehende Installationen muessen `model_gemini` in den Add-on-Optionen manuell auf einen aktuellen Wert setzen, der Code-Default greift nur bei leerem Feld
- `DOCS.md`: Hinweis ergaenzt, unter [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models) nachzusehen, falls das wieder passiert, sowie auf [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) zu pruefen, ob der eigene Key ueberhaupt echtes Free-Tier-Kontingent hat (EU/EWR/UK/Schweiz-Ausschluss, siehe bestehender Hinweis)

## 0.8.2

### Neu: Ollama-Timeouts loesen jetzt auch Cooldown aus, alle-erschoepft faellt sofort auf
- `router.py`: `parse_retry_after_seconds()` erkennt jetzt zusaetzlich generische Timeout-Fehler (bisher nur Kontingent-429 mit bekannter Reset-Zeit) und vergibt einen festen 60s-Cooldown - verhindert, dass eine Folgeanfrage nach einem haengenden Ollama sofort wieder die vollen 90s auf denselben Provider wartet
- Neue `all_providers_in_cooldown()`-Pruefung in `chat_completions()`: sind alle konfigurierten Provider aktuell als erschoepft markiert, lehnt der Router sofort mit klarer Fehlermeldung (inkl. geschaetzter fruehester Verfuegbarkeit) ab, statt trotzdem durch die ganze Kaskade zu laufen und am Ende doch bei Ollamas 90s-Timeout zu landen. Ein harter Override wird davon nicht beeinflusst - der wird immer versucht

## 0.8.1

### Neu: Notbremse gegen absurd grosse Anfragen
- Beobachtet auf dem echten Server: eine einzelne Anfrage mit ueber 135000 Tokens (60x der ueblichen Groesse, vermutlich eine ausufernde Konversationshistorie in Extended OpenAI Conversation) - schlug bei Groq/OpenRouter sofort mit `context_length_exceeded` fehl UND liess Ollama zusaetzlich 90s haengen, bevor der Client ueberhaupt eine Antwort bekam. Insgesamt weit ueber drei Minuten fuer eine von vornherein aussichtslose Anfrage
- `router.py`: neue `estimate_prompt_tokens()` (grobe Schaetzung: Zeichenlaenge/4) direkt nach dem Entity-Trimming, noch vor jedem Provider-Aufruf. Ueberschreitet die Anfrage `max_prompt_tokens_estimate` (Standard 20000, deutlich ueber normalen ~2000-2500 Tokens), wird sie sofort mit 400 abgelehnt statt durch die ganze Kaskade zu laufen. `0` deaktiviert die Bremse
- Nebenbei beobachtet (nicht in diesem Repo behoben, da Client-seitig): nach der grossen fehlgeschlagenen Anfrage feuerte derselbe Client dutzende identische Folgeanfragen in schneller Folge - der Response-Cache aus 0.8.0 hat das bereits vollstaendig abgefangen (alle als Cache-Treffer beantwortet, kein einziger zusaetzlicher Provider-Aufruf)

## 0.8.0

### Neu: Antwort-Cache gegen doppelte Retries, Grafana-Alert, Ollama-Tuning
- `router.py`: kurzes Antwort-Caching (`response_cache_seconds`, Standard 30s) - Cache-Key aus Modell + Anfrage-Text + der (bereits getrimmten) Geraete-Tabelle, ohne die sich staendig aendernde "Current Time"-Zeile. Verhindert, dass ein HA-Retry derselben Frage (auf dem echten Server beobachtet: "Wie ist der Status vom Hoftor" kurz hintereinander zweimal) ein zweites Mal Kontingent/Zeit verbraucht. Nur fuer nicht-streamende Erfolgsantworten, mit 0 deaktivierbar
- `build_litellm_config.py`: Ollamas Modell-Konfiguration bekommt `max_tokens: 512` - deckelt litellm-seitig num_predict als Sicherheitsnetz gegen ausufernde Generierungen, ohne normale Ein-Satz-Antworten zu kappen
- `grafana/provisioning/alerting/high-error-rate.yaml`: neue Alert-Regel "AI Gateway: hohe Fehlerquote" (>5 fehlgeschlagene Anfragen in 15 Minuten, 10 Minuten anhaltend) - gegen die echte Grafana-Instanz erstellt und verifiziert (`health: ok`), dann wieder entfernt und als Provisioning-Datei ins Repo uebernommen, damit sie bei jedem Rebuild automatisch mitkommt. Zeigt als Alarm in Grafanas Alerting-UI; fuer externe Benachrichtigungen (E-Mail/Webhook) muss noch ein Contact Point in Grafana selbst eingerichtet werden (nutzerspezifisch, nicht vorbelegbar)

## 0.7.0

### Neu: erschoepfte Provider proaktiv ueberspringen + weitere Prompt-Bereinigung
- `router.py`: neues Cooldown-Tracking (`_provider_cooldown_until`) - schlaegt eine Anfrage wegen eines Kontingent-Limits fehl, wird die Wartezeit direkt aus der Fehlermeldung geparst (Groqs "try again in Xs/Xm", OpenRouters `X-RateLimit-Reset`-Zeitstempel, `retry_after_seconds`) und der Provider fuer diese Zeit als erschoepft markiert. `resolve_target()` startet die Kaskade fuer Folgeanfragen dann direkt beim naechsten nicht bekannt erschoepften Provider, statt jedes Mal erneut auf zwei bereits tote Provider zu warten (bis zu ~35s zusaetzliche Latenz vor der Ollama-Antwort gespart). Kein bekanntes Muster in der Fehlermeldung -> es wird nichts geraten, Provider bleibt normal Teil der Kaskade. Braucht die geloggten Fehler aus der Metrics-Postgres, also an `enable_metrics: true` gekoppelt (wie der traffic-basierte Status-Sensor aus 0.5.9)
- `router.py`: zwei weitere Entity-Filterstufen (siehe 0.6.0) - `exclude_camera_motion_entities` (Standard an) entfernt Kamera-/Bewegungserkennungs-Helfer (z. B. Frigate-Blueprints) fest, unabhaengig vom erkannten Thema; ausserdem wird ein bekannter Prompt-Bug von Extended OpenAI Conversation bereinigt, der teils ein Python-Objekt-Repr (`ComputedNameType._singleton`) statt eines echten Alias-Namens einsetzt
- `providers.py`: neue `raw_model_to_provider_map()` - die Zuordnung vom rohen litellm-Modell-Kuerzel auf den Provider-Key war in `status_push.py` dupliziert, jetzt an einer Stelle geteilt (auch von `router.py`s Cooldown-Tracking genutzt)

## 0.6.0

### Neu: Weniger Tokens pro Anfrage - nur relevante Geraete an das Modell schicken
- Beobachtet auf dem echten Server (System-Prompt einer echten Anfrage direkt aus der Metrics-DB analysiert): Extended OpenAI Conversation schickt bei jeder Anfrage eine CSV-Tabelle ALLER fuer Assist freigegebenen Geraete mit - 173 Entities, davon 87 (50 %) im Zustand `unavailable`/`unknown` (dauerhaft offline/kaputte Geraete, die nie eine brauchbare Antwort liefern koennen). Allein diese Zeilen machten ~54 % der Geraete-Tabelle aus (~2150 von ~3960 Tokens) - bei Groqs 100k-Token-Tagesbudget also der groesste Hebel, um mehr echte Anfragen/Tag durch die Kaskade zu bekommen, bevor auf das langsamere Ollama zurueckgefallen wird
- `router.py`: neue `apply_entity_trimming()`, wird auf jede Anfrage angewendet, bevor sie an den gewaehlten Provider geht (unabhaengig vom Kaskaden-Provider)
  - `trim_unavailable_entities` (Standard **an**): entfernt Zeilen mit Zustand `unavailable`/`unknown` automatisch - kein manuelles Pflegen einer Ausschlussliste in HA noetig, Geraete tauchen von selbst wieder auf, sobald sie online sind
  - `filter_entities_by_topic` (Standard **aus**, experimentell): grobe Stichwort-Heuristik (`DOMAIN_KEYWORDS`) erkennt am Anfrage-Text ein Thema (z. B. "Tor" -> `binary_sensor`+`switch`) und behaelt nur passende Domains - erkennt sie nichts Eindeutiges, wird NICHT gefiltert, um keine fuer die Antwort noetige Entity zu verlieren
  - Beide Filter erkennen das CSV-Format defensiv an der exakten Kopfzeile `entity_id,name,state,aliases` - passt es nicht (z. B. nach einem Update von Extended OpenAI Conversation), bleibt der Prompt unveraendert

## 0.5.11

### Fix: Kaskade brach ab, sobald ein Zwischenglied (nicht der Primaerprovider) fehlschlug
- Regression aus 0.5.8: nach dem Entfernen von `default_fallbacks` bestand `fallbacks` nur noch aus einem einzigen Eintrag `{'provider-groq': ['provider-openrouter', 'provider-ollama']}` - auf dem echten Server beobachtet: schlug Groq fehl UND danach auch OpenRouter, brach die Anfrage komplett ab statt bei Ollama weiterzumachen (Log: `No fallback model group found for original model_group=provider-openrouter`)
- Ursache im litellm-Quellcode geprueft (`get_fallback_model_group()` in `router_utils/fallback_event_handlers.py`): bei jedem Fehlschlag wird ein Eintrag fuer GENAU DAS gerade fehlgeschlagene Modell gesucht, nicht fuer den urspruenglichen Primaerprovider - ein Eintrag nur fuer `provider-groq` deckt daher nicht ab, wenn `provider-openrouter` als Zwischenglied selbst fehlschlaegt
- `build_litellm_config.py`: `fallbacks` ist jetzt eine Kette mit je einem expliziten Eintrag pro Provider zum naechsten (`provider-groq`->`provider-openrouter`, `provider-openrouter`->`provider-ollama`, ...) - gegen die echte `get_fallback_model_group()`-Funktion verifiziert, jeder Hop loest jetzt korrekt auf, das letzte Glied bleibt bewusst ohne eigenen Eintrag (sauberer Abbruch statt Selbst-Fallback wie vor 0.5.8)

## 0.5.10

### Fix: Grafana-Zugriffs-URL/CSRF-Origins waren fest auf einen einzelnen Nutzer hartkodiert
- Code-Review vor dem Verpacken als installierbares Add-on: `run.sh` hatte `GF_SERVER_ROOT_URL` und `GF_SECURITY_CSRF_TRUSTED_ORIGINS` fest auf die private Tailscale-IP/Domain eines einzelnen Nutzers gesetzt (Ueberbleibsel aus 0.5.5-0.5.7) - fuer jeden anderen Nutzer (oder bei geaenderter IP) haette Grafana mit "origin not allowed" verweigert, ohne dass DOCS.md diesen Schritt ueberhaupt erwaehnt
- Neue optionale Add-on-Optionen `grafana_root_url` / `grafana_trusted_hostnames` - nur gesetzt, wenn der Nutzer sie explizit konfiguriert, sonst gelten Grafanas Standardwerte (passt fuer den normalen Fall: Zugriff ueber denselben Host wie HA)
- `status_push.py`: veralteten Docstring korrigiert, der noch einen separaten docker-compose-Stack beschrieb - Postgres laeuft seit 0.5.0 im selben Add-on-Container

## 0.5.9

### Fix: Status-Sensor hat die Free-Kontingente von Groq/OpenRouter fast komplett selbst verbraucht
- Beobachtet auf dem echten Server (Grafana-Postgres direkt abgefragt): ~4100 Provider-Anfragen in 24h, aber nur 1-2 unterscheidbare `trigger`-Werte - der Rest waren identische, alle ~60s wiederkehrende Test-Prompts ("Hello, how are you?" / "1+1?")
- Ursache: `status_push.py` pollt `GATEWAY_HEALTH_URL` (`/health`) jede Minute, das leitet 1:1 an LiteLLMs `/health` weiter - LiteLLM schickt dabei pro Aufruf eine **echte Test-Completion an jedes konfigurierte Modell**, nicht nur einen Connectivity-Check. Bei 1440 Polls/Tag x 3 Provider ergab das ~4300 synthetische Completions/Tag
- Reale Fehlermeldungen aus der DB bestaetigten den Effekt: Groq `tokens per day (TPD): Limit 100000, Used 95197` (bei ~5000 Tokens/Anfrage durch vollen HA-Tool-Kontext reichen dafuer nur ~20 echte Anfragen), OpenRouter `Rate limit exceeded: free-models-per-day` mit `X-RateLimit-Limit: 50` (ohne aufgeladene Credits nur 50 Anfragen/Tag) - beide Kontingente waren dadurch schon kurz nach Tagesbeginn verbraucht, jede echte Assist-Anfrage lief den Rest des Tages zwangslaeufig auf das langsamere lokale Ollama (bis zu 76s Antwortzeit beobachtet)
- `status_push.py`: neue `provider_status_from_traffic()` ermittelt den aktiven/ausgefallenen Provider stattdessen aus dem zuletzt geloggten echten Request pro Provider in der Metrics-Postgres (`requests`-Tabelle) - kostet keine zusaetzlichen Tokens/Requests. Der bisherige `/health`-Check bleibt nur noch als Fallback, wenn `enable_metrics` nicht aktiv ist (dann gibt es keine Traffic-Historie, aus der sich der Status ableiten liesse)

## 0.5.8

### Fix: Ollama-Fallback konnte sich selbst nochmal aufrufen (doppelter 90s-Timeout)
- Beobachtet auf dem echten Server (Grafana-Log): eine Tool-Call-Anfrage ("Welche Lichter sind an") kaskadierte bis zu Ollama, das nach 90s timeoutete - danach griff `litellm`s `default_fallbacks` (`= [fallback_chain[-1]]`, also `provider-ollama` selbst), weil Ollama als letztes Kaskadenglied keinen eigenen `fallbacks`-Eintrag hat - Ollama wurde dadurch ein zweites Mal 90s lang versucht, bevor die Anfrage (mit Verzoegerung von ueber 3 Minuten) doch noch durchging
- `build_litellm_config.py`: `default_fallbacks` entfernt - `router.py` ruft ausserhalb eines harten Overrides (`disable_fallbacks=True`) immer nur den primaeren Provider auf, nie ein Kaskaden-Zwischenglied direkt, `fallbacks: [{primary: [...]}]` deckt die komplette Kaskade bereits ab

## 0.5.7

### Fix: "origin not allowed" - 0.5.6 hatte falsches Format fuer csrf_trusted_origins
- Grafana-Quelle geprueft (`pkg/middleware/csrf/csrf.go`): der Wert wird an **Leerzeichen** gesplittet (nicht Komma) und nur der **reine Hostname ohne Schema/Port** wird verglichen (`url.Parse(origin).Hostname()`)
- 0.5.6 hatte `"http://100.97.34.101:3001,https://monitoring-ha-bridge.unity-dev.de"` gesetzt - wurde als ein einziger, nie matchender Eintrag interpretiert
- Jetzt korrekt: `GF_SECURITY_CSRF_TRUSTED_ORIGINS="100.97.34.101 monitoring-ha-bridge.unity-dev.de"`

## 0.5.6

### Fix: "origin not allowed" trotz gesetzter csrf_trusted_origins (0.5.5 reichte nicht)
- `csrf_trusted_origins` in 0.5.5 ohne Schema gesetzt (`100.97.34.101:3001`) - Grafanas URL-Parser liest den Teil vor dem ersten Doppelpunkt als Schema, eine IP-Adresse ist dafuer aber kein gueltiges Schema, wodurch der Eintrag nicht griff
- Jetzt mit vollem Schema: `http://100.97.34.101:3001,https://monitoring-ha-bridge.unity-dev.de`

## 0.5.5

### Fix: Grafana-Dashboard zeigte "no default database" und danach "origin not allowed"
- `grafana/provisioning/datasources/postgres.yml`: Grafana 13 liest das "Default Database"-Feld für Postgres-Datasources aus `jsonData.database`, nicht mehr nur aus dem Top-Level-Feld `database` — ohne das zeigte die UI "You do not currently have a default database configured", obwohl die eigentliche Verbindung über das Top-Level-Feld funktionierte
- `run.sh`: `GF_SERVER_ROOT_URL` und `GF_SECURITY_CSRF_TRUSTED_ORIGINS` gesetzt — ohne das vergleicht Grafanas CSRF-Check den `Origin`-Header des Browsers (z. B. `http://100.97.34.101:3001`) gegen den Default `localhost:3000` und lehnt Anfragen mit "origin not allowed" ab, da der Zugriff tatsächlich über die Tailscale-Bridge auf Port 3001 läuft

## 0.5.4

### Standard-OpenRouter-Modell erneut aktualisiert (wieder deprecated)
- `meta-llama/llama-3.3-70b-instruct:free` ist mittlerweile komplett aus dem OpenRouter-Katalog entfernt worden (404 "unavailable for free")
- Neuer Default: `openai/gpt-oss-20b:free` - gegen die aktuelle OpenRouter-Modelliste geprüft (`GET https://openrouter.ai/api/v1/models`, `:free`-Suffix + `supported_parameters` enthält `tools`), 131k Kontext
- **Betrifft nur Neuinstallationen** - wer `model_openrouter` bereits in den Add-on-Optionen gesetzt hat, muss den Wert manuell aktualisieren

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
