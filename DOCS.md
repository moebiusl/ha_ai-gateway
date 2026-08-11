# AI Gateway

Kostenloser, kaskadierender Ersatz für den Assist-Conversation-Agent: erst kostenlose Cloud-Kontingente (Gemini, Groq, OpenRouter), bei Fehler/Kontingent-Ende automatisch das nächste, ganz am Ende ein lokales Ollama-Modell. Technisch ein schlanker [LiteLLM](https://docs.litellm.ai/)-Proxy mit OpenAI-kompatiblem Endpunkt, verpackt als Home-Assistant-Add-on.

Dieses Add-on ersetzt **nicht** Assist selbst, sondern den "Conversation Agent" dahinter — es liefert nur das Gehirn, keine eigene Sprachsteuerung.

## Was du selbst einrichten musst

Das Add-on allein reicht nicht — es müssen noch drei Dinge dazukommen, die sich nicht per Add-on automatisieren lassen (plus zwei optionale Erweiterungen):

### 1. Kostenlose API-Keys besorgen (so viele wie du willst, auch nur einer reicht)

- **Gemini**: Key über Google AI Studio erstellen (Standard-Modell `gemini-3.6-flash`). **Modellverfügbarkeit ändert sich haeufig und ist teils kontospezifisch** — `gemini-2.0-flash` wurde im Juni 2026 komplett abgeschaltet, `gemini-2.5-flash` ist zwar noch allgemein gelistet, aber für neu angelegte Google-Cloud-Projekte/Keys gesperrt ("no longer available to new users" in der Fehlermeldung). Die allgemeine [Modell-Doku](https://ai.google.dev/gemini-api/docs/models) zeigt solche Konto-spezifischen Einschränkungen **nicht** zuverlässig — bei "model ... is no longer available" im Log am verlässlichsten direkt im [AI-Studio-Playground](https://aistudio.google.com/prompts/new_chat) nachsehen, welche Modelle für den eigenen Account in der Modellauswahl tatsächlich anwählbar sind, und `model_gemini` entsprechend setzen. **Wichtig:** Googles Gemini-API-Nutzungsbedingungen schließen das Gratis-Kontingent für Nutzer in der EU/EWR, UK und der Schweiz vertraglich aus — dort liefert jeder Key (unabhängig vom Google-Konto) dauerhaft `limit: 0` auf allen `free_tier`-Metriken, kein Bug, kein Workaround außer echtes Google-Cloud-Billing (siehe Kostenübersicht unten). Vor dem Eintragen des Keys unter [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) prüfen, ob echte Limits statt `0` angezeigt werden. Wer aus diesen Regionen zugreift und kein Billing aktivieren will, sollte `gemini_api_key` einfach leer lassen und sich auf Groq/OpenRouter/Ollama verlassen.

Bei aktiviertem Google-Cloud-Billing empfiehlt sich ein **Spend Cap** (Google Cloud Console → Budgets & alerts → Create new budget → "Spend cap enforcement" statt nur "Alerts", Service "Gemini API") als hartes Ausgabenlimit — pausiert die Nutzung automatisch, sobald das Budget erreicht ist, statt nur eine E-Mail zu schicken. Bei typischer Assist-Nutzung (siehe Token-Sparen oben) liegen die Kosten mit `gemini-3.6-flash` realistisch im niedrigen einstelligen Euro-Bereich pro Monat.
- **Groq**: Key über die Groq Console erstellen (kostenloses Kontingent, sehr schnelle Antworten für offene Modelle wie Llama 3.3)
- **OpenRouter**: Key über OpenRouter erstellen, dort gezielt ein Modell mit `:free`-Suffix wählen

Jeder dieser drei Keys ist optional. Trägst du keinen ein, wird der jeweilige Anbieter beim Start einfach übersprungen.

### 2. Ein Ollama-Add-on installieren (lokaler Fallback)

Dieses Add-on bringt **kein eigenes Ollama mit** — dafür gibt es bereits gepflegte Community-Add-ons. Im Add-on-Store nach einem Ollama-Add-on suchen (oder ein Community-Repository mit einem Ollama-Add-on hinzufügen), installieren, starten, und ein Tool-Calling-fähiges Modell laden, z. B.:

```
ollama pull qwen2.5:7b
```

Trage anschließend die interne Adresse dieses Add-ons unter **Konfiguration → `ollama_url`** ein (z. B. `http://<ollama-addon-hostname>:11434` — die genaue Hostname-Form steht in der README des jeweiligen Ollama-Add-ons).

### 3. "Extended OpenAI Conversation" per HACS installieren

Die offizielle "OpenAI Conversation"-Integration von Home Assistant unterstützt keine eigene Base-URL. Stattdessen:

1. [HACS](https://hacs.xyz/) installieren, falls noch nicht vorhanden
2. Custom Repository hinzufügen: `jekalmin/extended_openai_conversation`
3. Über HACS installieren, Home Assistant neu starten
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → Extended OpenAI Conversation**:
   - **Base URL**: `http://<ai-gateway-hostname>:4000/v1`
   - **API Key**: der `gateway_master_key`, den du unten in der Add-on-Konfiguration gesetzt hast
   - **Model**: ein beliebiger Wert, z. B. `assistant` — das Feld wird vom AI Gateway ohnehin überschrieben, es entscheidet selbst anhand von Kaskade/Override, welcher Provider tatsächlich antwortet
5. Unter **Einstellungen → Sprachassistenten** eine Pipeline anlegen/bearbeiten und als Conversation Agent "Extended OpenAI Conversation" wählen

### 4. Optional: manuellen Hart-Wechsel einrichten

Standardmäßig läuft die automatische Kaskade (Gemini → Groq → OpenRouter → Ollama). Willst du live erzwingen können, welcher Provider gerade antwortet, lege einmalig einen Dropdown-Helfer an:

1. **Einstellungen → Geräte & Dienste → Helfer → Helfer hinzufügen → Dropdown**
2. Entity-ID: `input_select.ai_gateway_provider_override` (oder eine andere — dann `provider_override_entity_id` unten anpassen)
3. Optionen exakt so anlegen: `Automatisch (Kaskade)`, `Gemini`, `Groq`, `OpenRouter`, `Ollama (lokal)`

Das Add-on fragt diesen Helfer alle paar Sekunden ab. Steht er auf einem bestimmten Provider, wird **kein** automatischer Fallback mehr versucht, selbst wenn dieser Provider gerade fehlschlägt — das ist der Sinn des harten Wechsels. Steht er auf "Automatisch" (oder fehlt/ist nicht verfügbar), läuft die normale Kaskade wie gewohnt.

### 5. Optional: Grafana-Dashboard mit Anfragen, Tokens, Antwortzeit

Postgres und Grafana laufen **im selben Add-on-Container mit** — nichts weiter zu installieren. Damit über denselben Weg erreichbar wie HA selbst (z. B. per VPN), ohne separaten Host.

1. Im AI-Gateway-Add-on unter **Konfiguration** `enable_metrics: true` setzen, optional `grafana_admin_password` (sonst gilt Grafanas Standard `admin` / `admin`, Passwortänderung wird beim ersten Login verlangt)
2. Add-on neu starten — beim ersten Start mit `enable_metrics: true` wird die Datenbank automatisch angelegt, Datenquelle und Dashboard sind bereits vorprovisioniert
3. Grafana öffnen: `http://<ha-host>:3001` (derselbe Host, auf dem auch Home Assistant läuft — über euer VPN also genauso erreichbar)

Das Dashboard "AI Gateway" ist sofort da und zeigt Anfragen über Zeit, Tokens pro Modell, Ø-Antwortzeit, Fehlerquote und eine Tabelle mit jeder Anfrage inklusive auslösendem Prompt und voller Antwort.

Postgres selbst ist **nicht** von außen erreichbar (nur `127.0.0.1` im Container) — einzig Grafanas Port 3001 ist nach außen offen.

**Nur falls "origin not allowed" im Browser erscheint** (typischerweise, wenn Grafana über eine andere Adresse aufgerufen wird als die, unter der HA selbst läuft — z. B. über eine separate VPN-/Tailscale-Bridge oder einen Reverse-Proxy mit eigenem Hostnamen): Grafana vergleicht den Origin-Header strikt gegen seine `root_url` und lehnt jede Abweichung ab. In dem Fall zusätzlich setzen:
- `grafana_root_url`: die volle URL, unter der Grafana tatsächlich erreicht wird, z. B. `http://100.97.34.101:3001/`
- `grafana_trusted_hostnames`: die dafür erlaubten Hostnamen, **ohne** Schema/Port, bei mehreren mit Leerzeichen getrennt, z. B. `100.97.34.101 grafana.example.internal`

Ohne diese beiden Optionen laufen Grafanas Standardwerte (passt für den normalen Fall, Zugriff über denselben Host wie HA).

## Add-on-Konfiguration

| Option | Beschreibung |
|---|---|
| `gemini_api_key` | Google-AI-Studio-Key, optional |
| `groq_api_key` | Groq-Console-Key, optional |
| `openrouter_api_key` | OpenRouter-Key, optional |
| `ollama_url` | Basis-URL des Ollama-Add-ons, z. B. `http://<hostname>:11434` |
| `gateway_master_key` | Beliebiges Passwort — schützt den Gateway-Endpunkt im internen Netz und wird als "API Key" in Extended OpenAI Conversation eingetragen |
| `model_gemini` / `model_groq` / `model_openrouter` / `model_ollama` | Welches Modell je Anbieter genutzt wird (Defaults sind ein sinnvoller Startpunkt, Verfügbarkeit ändert sich gelegentlich — bei Bedarf anpassen) |
| `status_sensor_entity_id` | Entity-ID des Status-Sensors in HA (Standard: `sensor.ai_gateway_active_provider`) |
| `provider_override_entity_id` | Entity-ID des Dropdown-Helfers für den Hart-Wechsel (Standard: `input_select.ai_gateway_provider_override`) |
| `enable_metrics` | Startet die mitgelieferte Postgres + Grafana (siehe Schritt 5), Standard `false` |
| `grafana_admin_password` | Optionales Admin-Passwort für Grafana, nur relevant wenn `enable_metrics` aktiv ist |
| `grafana_root_url` / `grafana_trusted_hostnames` | Nur bei "origin not allowed" nötig, siehe Schritt 5 |
| `trim_unavailable_entities` | Entfernt Geräte im Zustand `unavailable`/`unknown` automatisch aus dem an das Modell geschickten Prompt (siehe unten), Standard `true` |
| `exclude_camera_motion_entities` | Entfernt Kamera-/Bewegungserkennungs-Helfer (z. B. aus Frigate-Blueprints) fest aus dem Prompt, unabhängig vom Thema (siehe unten), Standard `true` |
| `filter_entities_by_topic` | Behält nur Geräte-Domains, die per Stichwort-Heuristik zur Anfrage passen (siehe unten), Standard `false` |
| `response_cache_seconds` | Wie lange identische Anfragen aus dem Cache beantwortet werden (siehe unten), Standard `30`, `0` deaktiviert den Cache |
| `max_prompt_tokens_estimate` | Lehnt Anfragen ueber dieser (grob geschaetzten) Tokenzahl sofort ab, statt sie durch die ganze Kaskade laufen zu lassen (siehe unten), Standard `20000`, `0` deaktiviert die Bremse |
| `gemini_daily_request_limit` | Fuer die geschaetzte `sensor.ai_gateway_gemini_quota_pct`-Anzeige (siehe Live-Status unten) - das eigene Tageslimit aus [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) eintragen, Standard `10000` |

Mindestens **ein** Provider (Cloud-Key oder `ollama_url`) muss gesetzt sein, sonst startet der Proxy nicht.

## Token-Sparen: nur relevante Geräte an das Modell schicken

Extended OpenAI Conversation schickt bei jeder Anfrage eine CSV-Tabelle **aller** für Assist freigegebenen Geräte mit ins Prompt. Der Router filtert das in mehreren unabhängig zuschaltbaren Stufen, bevor die Anfrage an den gewählten Provider geht — unabhängig vom Kaskaden-Provider, bei jeder Anfrage neu:

1. **`trim_unavailable_entities`** (Standard an): entfernt Geräte im Zustand `unavailable`/`unknown` — dauerhaft offline/kaputte Geräte liefern nie eine brauchbare Antwort, kosten aber trotzdem volle Tokens. Auf einem realen Setup mit vielen Integrationen waren über 50 % der Tabelle genau solche Zeilen. Kein manuelles Pflegen einer Ausschlussliste nötig: geht ein Gerät offline, verschwindet es automatisch; kommt es zurück, taucht es genauso automatisch wieder auf.
2. **`exclude_camera_motion_entities`** (Standard an): entfernt Entities, deren ID `motion_detected`, `person_detected`, `pet_detected` oder `camera_enabled` enthält (typische Frigate-/Kamera-Integrations-Helfer) — anders als die Themen-Heuristik unten eine feste, keine geratene Ausschlussliste, da diese Geräte nie per Sprachbefehl relevant sind.
3. **`filter_entities_by_topic`** (Standard aus, da experimentell): erkennt anhand fester deutscher Stichwörter im Anfrage-Text ein grobes Thema (z. B. "Lampe"/"Licht" → `light`, "Tür"/"Tor"/"Fenster" → `binary_sensor`/`cover`/`switch`, "Wetter"/"Temperatur" → `sensor`/`climate`) und behält nur Geräte aus den passenden Domains. Erkennt die Heuristik nichts Eindeutiges, wird **nicht** gefiltert — lieber zu viel Kontext schicken als eine Entity zu verlieren, die für die Antwort gebraucht wird. Die Stichwortliste steht als `DOMAIN_KEYWORDS` in `router.py` und lässt sich dort bei Bedarf erweitern.

Zusätzlich wird ein bekannter Prompt-Bug von Extended OpenAI Conversation bereinigt: manchmal landet ein Python-Objekt-Repr (`ComputedNameType._singleton`) statt eines echten Alias-Namens im `aliases`-Feld — reines Rauschen, wird automatisch geleert.

Alle Filter sind defensiv an das genaue CSV-Format von Extended OpenAI Conversation gekoppelt (Kopfzeile `entity_id,name,state,aliases` in einem ```csv```-Block) — passt das Format nicht (z. B. nach einem Update der Komponente), bleibt der Prompt unverändert, statt etwas falsch zu zerschneiden.

## Kaskade: bekannt erschöpfte Provider automatisch überspringen

Schlägt eine Anfrage wegen eines Kontingent-Limits fehl (Groq/OpenRouter-429-Antworten), liest der Router die Wartezeit direkt aus der Fehlermeldung des Providers (z. B. Groqs `"Please try again in 54m58s"` oder OpenRouters `X-RateLimit-Reset`-Zeitstempel) und merkt sich intern "dieser Provider ist bis dahin erschöpft". Folgeanfragen starten die Kaskade dann direkt beim nächsten noch nicht bekannt erschöpften Provider, statt jedes Mal erneut auf zwei bereits tote Provider zu warten (auf dem echten Server bis zu ~35 Sekunden zusätzliche Wartezeit vor jeder Ollama-Antwort).

Ein Timeout (z. B. Ollama unter Last oder nicht erreichbar) hat keine bekannte Reset-Zeit, bekommt aber einen festen, kurzen Cooldown von 60 Sekunden — sonst würde jede Folgeanfrage erneut die vollen 90 Sekunden auf denselben gerade hängenden Provider warten. Läuft die Cooldown-Zeit ab oder kommt kein bekanntes Muster in der Fehlermeldung vor, wird nichts geraten — der betroffene Provider bleibt normal Teil der Kaskade.

Sind **alle** konfigurierten Provider gerade als erschöpft markiert, lehnt der Router die Anfrage sofort mit einer klaren Fehlermeldung ab (inkl. Schätzung, wann der erste Provider wieder verfügbar ist), statt trotzdem durch die ganze Kaskade zu laufen und am Ende doch bei Ollamas 90s-Timeout zu landen. Ein harter Override (manuell gewählter Provider) wird davon nicht beeinflusst — der wird immer versucht, auch wenn er gerade auf Cooldown steht.

Dieser Mechanismus braucht die geloggten Fehler aus der Metrics-Postgres und ist daher an `enable_metrics: true` gekoppelt (wie auch der traffic-basierte Status-Sensor).

## Antwort-Cache: identische Anfragen nicht doppelt verarbeiten

Fragt HA (z. B. per Retry nach einem Timeout) dieselbe Frage kurz hintereinander nochmal, beantwortet der Router sie aus einem kurzen In-Memory-Cache statt erneut einen Provider aufzurufen — spart Kontingent und Zeit. Der Cache-Key besteht aus Modell + Anfrage-Text + der bereits gefilterten Geräte-Tabelle (ohne die sich bei jeder Anfrage ändernde "Current Time"-Zeile), sodass sich wirklich nur *inhaltlich identische* Anfragen treffen. Nur erfolgreiche, nicht-streamende Antworten werden gecacht.

`response_cache_seconds` (Standard `30`) steuert die Cache-Dauer; `0` deaktiviert den Cache komplett.

## Notbremse: absurd große Anfragen sofort ablehnen

Auf dem echten Server beobachtet: eine einzelne Anfrage mit über 135.000 Tokens (vermutlich eine ausufernde Konversationshistorie auf HA-/Extended-OpenAI-Conversation-Seite) — das ist bei Cloud-Anbietern mit ~128k-Kontextlimit von vornherein zum Scheitern verurteilt (`context_length_exceeded`) und ließ zusätzlich Ollama 90 Sekunden lang hängen, bevor der Client überhaupt eine Antwort bekam. Insgesamt kostete diese eine Anfrage weit über drei Minuten, ohne jede Chance auf Erfolg.

Der Router schätzt jetzt grob die Tokenzahl jeder Anfrage (Zeichenlänge ÷ 4, keine exakte Tokenizer-Berechnung, aber ausreichend um "offensichtlich kaputt groß" zu erkennen) und lehnt sie **sofort** ab, wenn sie `max_prompt_tokens_estimate` (Standard `20000`, deutlich über normalen ~2.000–2.500 Tokens einer getrimmten Anfrage) überschreitet — ganz ohne einen einzigen Provider anzufragen. `0` deaktiviert die Bremse.

## Grafana-Alert: hohe Fehlerquote

Bei aktivem `enable_metrics` ist eine Alert-Regel vorprovisioniert ("AI Gateway: hohe Fehlerquote", Ordner "AI Gateway" in Grafana): löst aus, wenn in den letzten 15 Minuten mehr als 5 Anfragen fehlgeschlagen sind und das mindestens 10 Minuten anhält (kurze Ausreißer wie ein einzelner Cloud-Kontingent-Fehlschlag lösen also nicht aus). Sichtbar direkt in Grafanas Alerting-Ansicht.

Für eine Benachrichtigung außerhalb von Grafana (E-Mail, Webhook an eine HA-Automation, …) muss in Grafana selbst unter **Alerting → Contact points** ein Kanal eingerichtet und der Regel zugeordnet werden — das ist nutzerspezifisch (SMTP-Zugangsdaten, Webhook-URL) und daher nicht vorprovisioniert.

## Lokales Modell schneller machen

Ein paar Stellschrauben für Ollama, unabhängig von diesem Add-on:

- **`keep_alive` im Ollama-Add-on erhöhen** (Standard oft nur wenige Minuten): läuft das Modell zwischen Anfragen aus dem Speicher, dauert die nächste Anfrage spürbar länger, weil es erst neu geladen werden muss. Ein längerer Wert (oder `-1` für dauerhaft geladen) vermeidet das.
- **Kleineres/schnelleres Modell testen** (z. B. eine 3B- statt 7B-Variante) — schneller auf CPU, ggf. etwas schwächer bei komplexeren Anfragen. Muss man fürs eigene Setup ausprobieren.
- **Kleinerer Prompt hilft doppelt**: die Entity-Filter oben (siehe "Token-Sparen") reduzieren nicht nur Cloud-Kontingent-Verbrauch, sondern auch Ollamas Verarbeitungszeit, da weniger Kontext eingelesen werden muss.
- Dieses Add-on deckelt zusätzlich `max_tokens` (512) für Ollama, als Sicherheitsnetz gegen ausufernde Generierungen, ohne normale kurze Antworten zu beeinflussen.

## Live-Status: welcher Anbieter gerade aktiv ist

Das Add-on legt automatisch die Entity `sensor.ai_gateway_active_provider` in Home Assistant an (Name über `status_sensor_entity_id` änderbar) und aktualisiert sie jede Minute:

- **State**: das tatsächlich verwendete Modell des aktiven Providers (z. B. `gemini/gemini-3.6-flash`, `groq/llama-3.3-70b-versatile` — LiteLLM meldet hier die konkrete Modell-Kennung, nicht unseren internen Alias)
- **Attribut `failed_providers`**: welche Provider gerade nicht erreichbar sind / deren Kontingent aufgebraucht ist
- **Attribut `override`**: aktueller Stand des Hart-Wechsel-Helfers (`Automatisch (Kaskade)` oder ein konkreter Provider)
- **Attribut `cooldowns`**: Provider, die aktuell wegen eines erkannten Kontingent-/Timeout-Fehlers übersprungen werden, mit geschätztem Ende (siehe "Kaskade: bekannt erschöpfte Provider automatisch überspringen" oben) — leer (`{}`), wenn alles normal läuft
- **Attribut `last_error`**: letzte Fehlermeldung, falls der Gateway selbst nicht erreichbar war

Ist `enable_metrics` aktiv, kommen zusätzlich diese Sensoren dazu:

- `sensor.ai_gateway_requests_today` / `sensor.ai_gateway_tokens_today` — Summen für den laufenden Tag, jeweils mit Attribut `by_provider` (Aufschlüsselung pro Provider, z. B. `{"gemini": 47, "groq": 3, "ollama": 2}`)
- `sensor.ai_gateway_avg_latency_ms` — Ø-Antwortzeit über alle Provider
- `sensor.ai_gateway_last_request` — State ist der Zeitpunkt der letzten Anfrage, Attribute: `provider`, `trigger` (auslösender Text), `success`, `latency_ms`, `tokens_in`, `tokens_out`
- `sensor.ai_gateway_gemini_quota_pct` — nur vorhanden, wenn Gemini konfiguriert ist. State ist eine **geschätzte** Prozentzahl der heute über Gemini gelaufenen Anfragen gegen `gemini_daily_request_limit` (Standard `10000`, in Google AI Studio unter [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) für den eigenen Account nachsehen und bei Bedarf anpassen). **Keine echte, von Google bestätigte Zahl** — Google bietet dafür keine API, nur die manuelle AI-Studio-Ansicht; die Schätzung basiert rein auf der eigenen geloggten Nutzung. Zeigt bewusst nur einen Prozentwert ohne jede Preis-/Kostenangabe

Alle diese Entities lassen sich wie jeder andere Sensor auf einem Dashboard anzeigen oder für eine Benachrichtigung nutzen (z. B. "benachrichtige mich, wenn `failed_providers` nicht leer ist" oder "wenn `sensor.ai_gateway_gemini_quota_pct` über 80 % steigt").

Ein fertiges Dashboard mit Status, Gemini-Kontingent-Anzeige, ausgefallenen/gedrosselten Providern, Tageskennzahlen je Provider und letzter Anfrage liegt unter [`examples/dashboard.yaml`](examples/dashboard.yaml) — Inhalt einfach per "In YAML bearbeiten" in ein neues oder bestehendes Dashboard übernehmen (Details dazu am Anfang der Datei).

## Sicherheit

Der Gateway-Port selbst (4000) wird **nicht** nach außen freigegeben — nur aus dem internen Home-Assistant-Netz erreichbar. Der `gateway_master_key` ist eine zusätzliche Zugriffsschranke innerhalb dieses internen Netzes. Ist `enable_metrics` aktiv, ist einzig Grafana (Port 3001) von außen erreichbar — mit Admin-Login (`grafana_admin_password` setzen, sonst Grafanas Standard-Login mit Passwortänderung beim ersten Zugriff). Die vollen Gesprächsinhalte landen dann im Klartext in der internen Postgres — das ist bewusst so gewünscht, aber die Datenbank selbst ist nach außen nicht erreichbar (nur Grafana als Zugriffsweg darauf).
