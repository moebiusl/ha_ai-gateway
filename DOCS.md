# AI Gateway

Kostenloser, kaskadierender Ersatz für den Assist-Conversation-Agent: erst kostenlose Cloud-Kontingente (Gemini, Groq, OpenRouter), bei Fehler/Kontingent-Ende automatisch das nächste, ganz am Ende ein lokales Ollama-Modell. Technisch ein schlanker [LiteLLM](https://docs.litellm.ai/)-Proxy mit OpenAI-kompatiblem Endpunkt, verpackt als Home-Assistant-Add-on.

Dieses Add-on ersetzt **nicht** Assist selbst, sondern den "Conversation Agent" dahinter — es liefert nur das Gehirn, keine eigene Sprachsteuerung.

## Was du selbst einrichten musst

Das Add-on allein reicht nicht — es müssen noch drei Dinge dazukommen, die sich nicht per Add-on automatisieren lassen (plus zwei optionale Erweiterungen):

### 1. Kostenlose API-Keys besorgen (so viele wie du willst, auch nur einer reicht)

- **Gemini**: Key über Google AI Studio erstellen (kostenloses Kontingent für `gemini-2.0-flash` o.ä.)
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

Läuft komplett als Home-Assistant-Add-ons mit — dadurch über denselben Weg erreichbar wie HA selbst (z. B. per VPN), kein separater Host/Port nötig.

1. **Postgres-Add-on installieren**: Repository `https://github.com/expaso/hassos-addons` hinzufügen, das PostgreSQL-Add-on installieren, Admin-Zugangsdaten (Nutzer/Passwort/Datenbank) in dessen Konfiguration vergeben, starten.
2. **Grafana-Add-on installieren**: Repository `https://github.com/hassio-addons/addon-grafana` hinzufügen, installieren, starten. Erscheint danach mit Ingress in der HA-Seitenleiste — Login läuft automatisch über HA (kein separates Passwort nötig).
3. Im AI-Gateway-Add-on unten `metrics_db_url` eintragen, z. B. `postgresql://<user>:<passwort>@<postgres-addon-hostname>:5432/<db>` (Hostname steht wie bei Ollama auf der Info-Seite des Postgres-Add-ons). AI Gateway legt die benötigte Tabelle beim Start selbst an.
4. In Grafana (über die Seitenleiste öffnen) einmalig:
   - **Datenquelle hinzufügen** → PostgreSQL → dieselben Zugangsdaten wie in Schritt 3
   - **Dashboard importieren** → die Datei [`grafana/ai-gateway-overview.json`](grafana/ai-gateway-overview.json) aus diesem Repo hochladen, die eben angelegte Datenquelle auswählen

Das Dashboard zeigt danach Anfragen über Zeit, Tokens pro Modell, Ø-Antwortzeit, Fehlerquote und eine Tabelle mit jeder Anfrage inklusive auslösendem Prompt und voller Antwort.

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
| `metrics_db_url` | Vollständige Postgres-URL des Postgres-Add-ons (siehe Schritt 5), optional — leer heißt kein Logging, keine Kennzahlen-Sensoren |

Mindestens **ein** Provider (Cloud-Key oder `ollama_url`) muss gesetzt sein, sonst startet der Proxy nicht.

## Live-Status: welcher Anbieter gerade aktiv ist

Das Add-on legt automatisch die Entity `sensor.ai_gateway_active_provider` in Home Assistant an (Name über `status_sensor_entity_id` änderbar) und aktualisiert sie jede Minute:

- **State**: das tatsächlich verwendete Modell des aktiven Providers (z. B. `gemini/gemini-2.0-flash`, `groq/llama-3.3-70b-versatile` — LiteLLM meldet hier die konkrete Modell-Kennung, nicht unseren internen Alias)
- **Attribut `failed_providers`**: welche Provider gerade nicht erreichbar sind / deren Kontingent aufgebraucht ist
- **Attribut `override`**: aktueller Stand des Hart-Wechsel-Helfers (`Automatisch (Kaskade)` oder ein konkreter Provider)
- **Attribut `last_error`**: letzte Fehlermeldung, falls der Gateway selbst nicht erreichbar war

Ist `metrics_db_url` gesetzt, kommen zusätzlich diese Sensoren dazu (Kennzahlen für den laufenden Tag):

- `sensor.ai_gateway_requests_today`
- `sensor.ai_gateway_tokens_today`
- `sensor.ai_gateway_avg_latency_ms`

Alle diese Entities lassen sich wie jeder andere Sensor auf einem Dashboard anzeigen oder für eine Benachrichtigung nutzen (z. B. "benachrichtige mich, wenn `failed_providers` nicht leer ist").

## Sicherheit

Das Add-on gibt **keinen** externen Port frei — es ist absichtlich nur aus dem internen Home-Assistant-Netz erreichbar, nicht vom LAN. Der `gateway_master_key` ist eine zusätzliche Zugriffsschranke innerhalb dieses internen Netzes. Die vollen Gesprächsinhalte landen (sofern `metrics_db_url` gesetzt ist) im Klartext in der Postgres-Datenbank — das ist bewusst so gewünscht, aber auch das Postgres-Add-on entsprechend absichern (Zugangsdaten nicht mit anderen Diensten teilen).
