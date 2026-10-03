# Velora für iPhone

Native SwiftUI-App für das Velora-Dashboard. Sie spricht mit demselben Server (Pi) wie die Web-App, über die JSON-Endpunkte unter `/api/app/*` sowie die bestehenden Schreib- und Chat-Routen.

## Projekt öffnen

Das Xcode-Projekt wird aus `project.yml` erzeugt:

```bash
cd ios
xcodegen generate
open Velora.xcodeproj
```

## Auf dem eigenen iPhone installieren (kostenloser Apple-Account)

1. In Xcode › Settings › Accounts mit der Apple-ID anmelden.
2. Falls nötig in `project.yml` `BUNDLE_ID_BASE` auf etwas Eindeutiges setzen, dann `xcodegen generate`.
3. Im Target **Velora** unter *Signing & Capabilities* das Personal Team wählen.
4. iPhone per Kabel verbinden, als Ziel wählen, ▶︎ starten. Am iPhone: Einstellungen › Allgemein › VPN & Geräteverwaltung › Entwickler vertrauen.
5. Beim ersten Start „Lokales Netzwerk“ erlauben – sonst erreicht die App den Pi im WLAN nicht.

Mit dem kostenlosen Account läuft die App 7 Tage und muss dann neu aus Xcode installiert werden.

## Verbindung

In der App unter Übersicht › ⚙︎:

- **Heim-WLAN**: `http://192.168.1.27:8080` (vorbelegt)
- **Tailscale**: Adresse des Pi im Tailnet, z. B. `http://rockpi:8080` oder `http://100.x.y.z:8080`
- **Passwort**: nur, wenn am Pi `web.auth_token` in `settings.json` gesetzt ist

Die App probiert zuerst kurz die WLAN-Adresse und nimmt sonst Tailscale; bei jedem Netzwechsel wird neu entschieden. Ohne Verbindung zeigt sie den zuletzt geladenen Stand.

Push-Benachrichtigungen gibt es mit dem kostenlosen Account nicht. Briefings kommen weiter über Telegram bzw. die Web-App.

## Aufbau

| Ordner | Inhalt |
|---|---|
| `VeloraKit` | Swift-Paket ohne UI: Modelle der API-Antworten, Netzwerk-Client (WLAN/Tailscale, SSE-Chat), Formatierung |
| `Velora/Model` | App-Zustand, Antwort-Zwischenspeicher, Schlüsselbund |
| `Velora/Views` | Übersicht, Depot (Positionen, Performance, Steuer, Stops, Orders), Markt, Berater (Briefings, Empfehlungen), Chat, Strategie, Durchschau, Einstellungen |

## Tests

```bash
cd ios/VeloraKit
swift test
```

Mit echten Server-Antworten (z. B. per `curl` gespeichert als `dashboard.json`, `portfolio.json`, …):

```bash
VELORA_API_DUMP=/pfad/zum/ordner swift test
```

Serverseitig deckt `tests/test_app_api.py` die `/api/app/*`-Endpunkte ab.
