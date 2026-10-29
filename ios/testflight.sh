#!/usr/bin/env bash
# Baut Velora als Release und lädt den Build zu TestFlight hoch.
# Nur mit bezahltem Apple-Developer-Account und angelegter App in App Store Connect.
#
#   ios/testflight.sh
#
# Team und Bundle-ID kommen aus Config/Local.xcconfig (Vorlage: Config/Local.xcconfig.example).
#
# Danach verarbeitet Apple den Build (5–15 min); er erscheint dann von selbst in der
# TestFlight-App am iPhone. Builds laufen nach 90 Tagen ab – rechtzeitig neu hochladen.
#
# Signieren und Hochladen laufen über die Apple-ID, die in Xcode angemeldet ist
# (Account Holder – der App-Store-Connect-API-Schlüssel mit Rolle „App Manager“ darf
# keine Distributionszertifikate verwenden). Optional: Ist in config/settings.json
# → app_store_connect ein API-Schlüssel eingetragen, wartet das Skript auf die
# Verarbeitung durch Apple.
set -euo pipefail

cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

xcodegen generate --quiet

# Xcode ruft /usr/bin/rsync auf; ein Homebrew-rsync weiter vorne im PATH bricht den
# Export mit „Copy failed“ ab. Für xcodebuild deshalb nur die Systemwerkzeuge.
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

# TestFlight verlangt bei jedem Upload eine höhere Build-Nummer (je Teil < 2^31).
BUILD="$(date +%Y%m%d).$(date +%H%M)"
ARCHIVE="build/Velora.xcarchive"
EXPORT="build/export"
rm -rf "$ARCHIVE" "$EXPORT"

echo "▸ Archiv bauen (Build $BUILD) …"
xcodebuild -project Velora.xcodeproj -scheme Velora -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$ARCHIVE" \
  CURRENT_PROJECT_VERSION="$BUILD" -allowProvisioningUpdates -quiet archive

cat > build/ExportOptions.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>signingStyle</key><string>automatic</string>
  <key>uploadSymbols</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict>
</plist>
EOF

echo "▸ Signieren und zu App Store Connect hochladen …"
xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist build/ExportOptions.plist \
  -exportPath "$EXPORT" -allowProvisioningUpdates -quiet

echo "✓ Build $BUILD hochgeladen."
"$REPO/venv/bin/python" - "$REPO" "$BUILD" <<'EOF'
import json, sys, time
from pathlib import Path

repo, build = Path(sys.argv[1]), sys.argv[2]
settings = repo / "config/settings.json"
asc = (json.loads(settings.read_text()) if settings.exists() else {}).get("app_store_connect", {})
if not all(asc.get(k) for k in ("key_path", "key_id", "issuer_id", "app_id")):
    print("Apple verarbeitet ihn jetzt (5–15 min); danach erscheint er in TestFlight.")
    sys.exit(0)

import httpx, jwt
print("Warte auf die Verarbeitung durch Apple …")
key_path = Path(asc["key_path"])
key = (key_path if key_path.is_absolute() else repo / key_path).read_text()

def token():
    now = int(time.time())
    return jwt.encode({"iss": asc["issuer_id"], "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
                      key, algorithm="ES256", headers={"kid": asc["key_id"], "typ": "JWT"})

for _ in range(40):  # bis zu 20 min
    r = httpx.get("https://api.appstoreconnect.apple.com/v1/builds",
                  params={"filter[app]": asc["app_id"], "filter[version]": build},
                  headers={"Authorization": f"Bearer {token()}"}, timeout=30)
    data = r.json().get("data", [])
    state = data[0]["attributes"]["processingState"] if data else "noch nicht sichtbar"
    if state == "VALID":
        print(f"✓ Build {build} ist in TestFlight bereit.")
        break
    if state in ("FAILED", "INVALID"):
        sys.exit(f"✕ Apple hat Build {build} abgelehnt ({state}) – E-Mail von App Store Connect prüfen.")
    time.sleep(30)
else:
    print(f"… Build {build} wird noch verarbeitet ({state}); er erscheint später von selbst in TestFlight.")
EOF
