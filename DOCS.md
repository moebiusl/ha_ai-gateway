# AI Gateway

Kostenloser, kaskadierender Ersatz für den Assist-Conversation-Agent: erst kostenlose Cloud-Kontingente (Gemini, Groq, OpenRouter), bei Fehler/Kontingent-Ende automatisch das nächste, ganz am Ende ein lokales Ollama-Modell. Technisch ein schlanker [LiteLLM](https://docs.litellm.ai/)-Proxy mit OpenAI-kompatiblem Endpunkt, verpackt als Home-Assistant-Add-on.

Dieses Add-on ersetzt **nicht** Assist selbst, sondern den "Conversation Agent" dahinter — es liefert nur das Gehirn, keine eigene Sprachsteuerung.

## Was du selbst einrichten musst

Das Add-on allein reicht nicht — es müssen noch drei Dinge dazukommen, die sich nicht per Add-on automatisieren lassen (plus zwei optionale Erweiterungen):

### 1. Kostenlose API-Keys besorgen (so viele wie du willst, auch nur einer reicht)

- **Gemini**: Key über Google AI Studio erstellen (kostenloses Kontingent für `gemini-2.0-flash` o.ä.). **Wichtig:** Googles Gemini-API-Nutzungsbedingungen schließen das Gratis-Kontingent für Nutzer in der EU/EWR, UK und der Schweiz vertraglich aus — dort liefert jeder Key (unabhängig vom Google-Konto) dauerhaft `limit: 0` auf allen `free_tier`-Metriken, kein Bug, kein Workaround außer echtes Google-Cloud-Billing. Wer aus diesen Regionen zugreift, sollte `gemini_api_key` einfach leer lassen und sich auf Groq/OpenRouter/Ollama verlassen.
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

Mindestens **ein** Provider (Cloud-Key oder `ollama_url`) muss gesetzt sein, sonst startet der Proxy nicht.

## Live-Status: welcher Anbieter gerade aktiv ist

Das Add-on legt automatisch die Entity `sensor.ai_gateway_active_provider` in Home Assistant an (Name über `status_sensor_entity_id` änderbar) und aktualisiert sie jede Minute:

- **State**: das tatsächlich verwendete Modell des aktiven Providers (z. B. `gemini/gemini-2.0-flash`, `groq/llama-3.3-70b-versatile` — LiteLLM meldet hier die konkrete Modell-Kennung, nicht unseren internen Alias)
- **Attribut `failed_providers`**: welche Provider gerade nicht erreichbar sind / deren Kontingent aufgebraucht ist
- **Attribut `override`**: aktueller Stand des Hart-Wechsel-Helfers (`Automatisch (Kaskade)` oder ein konkreter Provider)
- **Attribut `last_error`**: letzte Fehlermeldung, falls der Gateway selbst nicht erreichbar war

Ist `enable_metrics` aktiv, kommen zusätzlich diese Sensoren dazu (Kennzahlen für den laufenden Tag):

- `sensor.ai_gateway_requests_today`
- `sensor.ai_gateway_tokens_today`
- `sensor.ai_gateway_avg_latency_ms`

Alle diese Entities lassen sich wie jeder andere Sensor auf einem Dashboard anzeigen oder für eine Benachrichtigung nutzen (z. B. "benachrichtige mich, wenn `failed_providers` nicht leer ist").

## Sicherheit

Der Gateway-Port selbst (4000) wird **nicht** nach außen freigegeben — nur aus dem internen Home-Assistant-Netz erreichbar. Der `gateway_master_key` ist eine zusätzliche Zugriffsschranke innerhalb dieses internen Netzes. Ist `enable_metrics` aktiv, ist einzig Grafana (Port 3001) von außen erreichbar — mit Admin-Login (`grafana_admin_password` setzen, sonst Grafanas Standard-Login mit Passwortänderung beim ersten Zugriff). Die vollen Gesprächsinhalte landen dann im Klartext in der internen Postgres — das ist bewusst so gewünscht, aber die Datenbank selbst ist nach außen nicht erreichbar (nur Grafana als Zugriffsweg darauf).
