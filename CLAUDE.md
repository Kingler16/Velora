# Velora – Projektregeln

Velora ist ein **öffentliches** GitHub-Repo (github.com/Kingler16/Velora). Der Code muss für
jeden funktionieren, der es klont – nicht nur für das Setup des Besitzers. Gleichzeitig ist
das Setup des Besitzers der wichtigste Nutzer: Änderungen dürfen es nie verschlechtern.
Persönliche Details dazu stehen in `CLAUDE.local.md` (gitignoriert, falls vorhanden).

## Alle Wege bleiben optional

Das Web-Dashboard läuft immer. Alles andere ist optional und muss einzeln an- und abschaltbar
bleiben:

| Kanal | Konfiguration | Wenn nicht konfiguriert |
|---|---|---|
| Telegram (Bot + Nachrichten) | `settings.json` → `telegram` | Kein Versand, Bot-Dienst wird nicht eingerichtet |
| Browser-Push (Web-App) | `settings.json` → `web_push` (VAPID) | Still übersprungen |
| iOS-App mit kostenlosem Apple-Account | `ios/Config/Local.xcconfig` ohne `CODE_SIGN_ENTITLEMENTS` | App fragt nicht nach Mitteilungen |
| iOS-App mit bezahltem Account + Push | `Local.xcconfig` mit Entitlements, `settings.json` → `apns` | — |
| TestFlight-Upload | `ios/testflight.sh`, optional `settings.json` → `app_store_connect` | Skript lädt hoch, ohne auf Apple zu warten |

Regeln daraus:
- Neue Funktionen sind konfigurationsgesteuert und überspringen sich still (mit Log-Zeile),
  wenn ihre Konfiguration fehlt – nie abstürzen, nie einen Kanal voraussetzen.
- Mitteilungen laufen über `send_push`/`send_push_safe` (Kategorien + Schalter aus
  `notification_preferences`), Systemfehler über `src/delivery/alerts.py`. Telegram ist ein
  Kanal unter mehreren, nicht der Standard.
- Neue Einstellungen gehören in `config/settings.example.json`, neue Kanäle zusätzlich in den
  Setup-Assistenten (`setup.py`) und ins README.
- Server-Installation: `scripts/setup_server.sh` (allgemein, kein fest verdrahteter User/Pfad/Host).

## Keine persönlichen Daten im Repo

Nie in getrackte Dateien (Code, Tests, Kommentare, Doku, Commit-Messages):
Namen, E-Mail-Adressen, IPs, Hostnamen, Tailnet-Namen, Apple-Team-IDs, eigene Bundle-IDs,
Schlüssel-IDs, Tokens, Passwörter, echte Konto-Keys, Ticker/ISINs/Beträge aus dem echten Depot.

Stattdessen Beispielwerte: `com.example.velora`, `ABCDE12345`, `192.168.1.10`, `100.64.0.5`,
`main_broker`/`broker_cash`, `AT0000A00001`, `you@example.com`.

Persönliches gehört in gitignorierte Dateien: `config/settings.json`, `config/portfolio.json`,
`config/mandate.json`, `config/keys/`, `memory/`, `ios/Config/Local.xcconfig`, `.env`,
`CLAUDE.local.md`.

Vor jedem Commit den Diff auf solche Daten prüfen (`git diff --cached`). Eine öffentliche
Historie lässt sich nur per Force-Push bereinigen – lieber gar nicht erst committen.

## Konventionen

- Code-Kommentare und UI-Texte (App, Web) auf Deutsch, README/Anleitungen für GitHub auf Englisch.
- Tests: `./venv/bin/python -m pytest -q` und `cd ios/VeloraKit && swift test`
  (mit `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`, falls `xcode-select` auf die
  CommandLineTools zeigt).
- Das Xcode-Projekt wird aus `ios/project.yml` erzeugt (`xcodegen generate`); Signierung kommt
  aus `ios/Config/Base.xcconfig` + `Local.xcconfig`.
- Laufzeitdaten (Portfolio, Chats, Memory) nie löschen oder überschreiben; Schema-Änderungen
  nur additiv (`CREATE TABLE IF NOT EXISTS`, neue Felder mit Default).
