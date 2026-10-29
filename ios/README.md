# Velora for iPhone

Native SwiftUI app for your own Velora server. It talks to the same server as the web dashboard (JSON endpoints under `/api/app/*` plus the existing write and chat routes). The app UI is German.

The app is **not** in the App Store. You build it yourself with Xcode. Pick the path that fits you:

| | Free Apple account | Paid Apple Developer Program (99 $/year) |
|---|---|---|
| Install | Xcode → iPhone via cable | TestFlight (or Xcode) |
| Valid for | 7 days, then reinstall | TestFlight builds 90 days, re-upload any time |
| Push notifications | – (briefings stay in the app, Telegram or browser push) | ✓ via APNs |

You don't need the iOS app at all: the web dashboard works in any browser and can be installed on the home screen.

## 1. Configure signing

```bash
cd ios
cp Config/Local.xcconfig.example Config/Local.xcconfig   # gitignored – your values stay local
```

In `Config/Local.xcconfig`:

- `DEVELOPMENT_TEAM`: your team ID (Xcode › Settings › Accounts › your Apple ID). For a free account this is your "Personal Team".
- `BUNDLE_ID_BASE`: something unique, e.g. `com.yourname.velora`
- `CODE_SIGN_ENTITLEMENTS = Velora/Velora.entitlements`: **only** with a paid account (enables push). Leave it out with a free account, or signing fails.
- `VELORA_DEFAULT_SERVER`: optional, the server address that's prefilled on first launch

Then generate the project (needs [XcodeGen](https://github.com/yonaskolb/XcodeGen), `brew install xcodegen`):

```bash
xcodegen generate
open Velora.xcodeproj
```

## 2a. Install with a free account

1. Connect your iPhone, select it as the run destination, press ▶︎.
2. On the iPhone: Settings › General › VPN & Device Management › trust the developer.
3. On first launch allow "Local Network", otherwise the app can't reach your server on Wi-Fi.

After 7 days the app stops launching. Press ▶︎ again in Xcode.

## 2b. TestFlight with a paid account

1. [App Store Connect](https://appstoreconnect.apple.com) › Apps › "+": new iOS app with your bundle ID. The name must be unique in the whole App Store; the home-screen name stays "Velora".
2. Make sure Xcode is signed in with the Apple ID of the account holder or an admin (only those may use distribution certificates).
3. Upload a build:
   ```bash
   ios/testflight.sh
   ```
   Every upload gets a new build number (`YYYYMMDD.HHMM`). Optional: put an App Store Connect API key into `config/settings.json` → `app_store_connect` (see `config/settings.example.json`) and the script waits until Apple has processed the build.
4. App Store Connect › your app › TestFlight › Internal Testing "+": tick "automatically distribute to all builds", add yourself. Install via the TestFlight app on the iPhone.

## 3. Push notifications (paid account only)

1. [Apple Developer](https://developer.apple.com/account/resources/authkeys/list) › Keys › "+" › Apple Push Notifications service (APNs). The `.p8` file can be downloaded **once**. Put it on your server, e.g. `config/keys/` (gitignored).
2. On the server in `config/settings.json`:
   ```json
   "apns": {
     "key_path": "config/keys/AuthKey_XXXXXXXXXX.p8",
     "key_id": "XXXXXXXXXX",
     "team_id": "ABCDE12345",
     "bundle_id": "com.yourname.velora"
   }
   ```
3. Restart the web service. On first launch the app asks for permission and registers itself with the server. Settings › Mitteilungen › "Test-Mitteilung senden" checks the whole chain.

Notes:
- APNs keys can be limited to production or sandbox. Builds from Xcode use **sandbox** tokens, TestFlight builds use **production**. A production-only key therefore only works with TestFlight builds.
- Which events notify you (briefings, chat replies, trades, …) can be switched per category in the app settings or on the web settings page. The switches apply to browser push as well.

## Connection

In the app under Übersicht › ⚙︎:

- **Heim-WLAN**: address of your server on your home network, e.g. `http://192.168.1.10:8080`
- **Tailscale**: address of the server in your tailnet for use on the go, e.g. `http://velora-server:8080` or `http://100.x.y.z:8080`
- **Passwort**: only if `web.auth_token` is set in the server's `settings.json`

The app first tries the Wi-Fi address and otherwise uses Tailscale; it decides again on every network change. Offline it shows the last loaded state.

## Structure

| Folder | Contents |
|---|---|
| `VeloraKit` | Swift package without UI: API models, network client (Wi-Fi/Tailscale, SSE chat), formatting, notification routing |
| `Velora/Model` | App state, response cache, keychain, push registration |
| `Velora/Views` | Overview, portfolio, market, advisor (briefings, recommendations), chat, strategy, look-through, settings |
| `Config` | `Base.xcconfig` (public defaults) + your `Local.xcconfig` |

## Tests

```bash
cd ios/VeloraKit
swift test
```

With real server responses (e.g. saved via `curl` as `dashboard.json`, `portfolio.json`, …):

```bash
VELORA_API_DUMP=/path/to/folder swift test
```

On the server side, `tests/test_app_api.py` and `tests/test_push_apns.py` cover the app endpoints and push delivery.
