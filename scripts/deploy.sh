#!/bin/bash
# Velora — Deploy to remote server
#
# Usage:
#   bash scripts/deploy.sh [user@host]           — nur Code/Templates/Static, KEINE Live-State-Files
#   bash scripts/deploy.sh [user@host] --with-config — zusätzlich settings/portfolio/watchlist kopieren (GEFÄHRLICH auf Live-Systemen, überschreibt remote state!)
set -e

REMOTE="$1"
if [ -z "$REMOTE" ] || [ "${REMOTE#-}" != "$REMOTE" ]; then
    echo "Usage: bash scripts/deploy.sh user@host [--with-config]" >&2
    exit 1
fi
REMOTE_DIR="/home/$(echo $REMOTE | cut -d@ -f1)/velora"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WITH_CONFIG=0
for arg in "$@"; do
    if [ "$arg" = "--with-config" ]; then WITH_CONFIG=1; fi
done

echo "=== Deploying Velora to $REMOTE:$REMOTE_DIR ==="
if [ "$WITH_CONFIG" = "1" ]; then
    echo "⚠ --with-config aktiv: portfolio.json, watchlist.json, settings.json werden ÜBERSCHRIEBEN."
fi

# 1. Verzeichnisstruktur erstellen
echo "Creating directories..."
ssh $REMOTE "mkdir -p $REMOTE_DIR/{config,memory/cache,logs,scripts}"
ssh $REMOTE "mkdir -p $REMOTE_DIR/src/{data,analysis,delivery,chat,web/{routes,services,templates/components,static/{css,js,vendor,icons}}}"

# 2. Source-Code kopieren
echo "Copying source code..."
scp -r "$LOCAL_DIR"/src/data/*.py $REMOTE:$REMOTE_DIR/src/data/
scp -r "$LOCAL_DIR"/src/analysis/*.py $REMOTE:$REMOTE_DIR/src/analysis/
scp -r "$LOCAL_DIR"/src/delivery/*.py $REMOTE:$REMOTE_DIR/src/delivery/
scp -r "$LOCAL_DIR"/src/chat/*.py $REMOTE:$REMOTE_DIR/src/chat/
scp "$LOCAL_DIR"/src/__init__.py $REMOTE:$REMOTE_DIR/src/
scp "$LOCAL_DIR"/src/main.py $REMOTE:$REMOTE_DIR/src/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/config_loader.py $REMOTE:$REMOTE_DIR/src/ 2>/dev/null || true

# 3. Web-Dashboard kopieren
echo "Copying web dashboard..."
scp "$LOCAL_DIR"/src/web/__init__.py $REMOTE:$REMOTE_DIR/src/web/
scp "$LOCAL_DIR"/src/web/app.py $REMOTE:$REMOTE_DIR/src/web/
scp "$LOCAL_DIR"/src/web/i18n.py $REMOTE:$REMOTE_DIR/src/web/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/web/routes/*.py $REMOTE:$REMOTE_DIR/src/web/routes/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/web/services/*.py $REMOTE:$REMOTE_DIR/src/web/services/
scp "$LOCAL_DIR"/src/web/templates/*.html $REMOTE:$REMOTE_DIR/src/web/templates/
scp "$LOCAL_DIR"/src/web/templates/components/*.html $REMOTE:$REMOTE_DIR/src/web/templates/components/
scp "$LOCAL_DIR"/src/web/static/css/*.css $REMOTE:$REMOTE_DIR/src/web/static/css/
scp "$LOCAL_DIR"/src/web/static/js/*.js $REMOTE:$REMOTE_DIR/src/web/static/js/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/web/static/vendor/*.js $REMOTE:$REMOTE_DIR/src/web/static/vendor/
scp "$LOCAL_DIR"/src/web/static/vendor/*.css $REMOTE:$REMOTE_DIR/src/web/static/vendor/ 2>/dev/null || true
# Top-level static files (logo, favicons)
scp "$LOCAL_DIR"/src/web/static/*.svg "$LOCAL_DIR"/src/web/static/*.png $REMOTE:$REMOTE_DIR/src/web/static/ 2>/dev/null || true
# PWA-Assets (manifest, service worker, offline fallback, icons)
scp "$LOCAL_DIR"/src/web/static/manifest.webmanifest $REMOTE:$REMOTE_DIR/src/web/static/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/web/static/sw.js              $REMOTE:$REMOTE_DIR/src/web/static/ 2>/dev/null || true
scp "$LOCAL_DIR"/src/web/static/offline.html       $REMOTE:$REMOTE_DIR/src/web/static/ 2>/dev/null || true
scp -r "$LOCAL_DIR"/src/web/static/icons/* $REMOTE:$REMOTE_DIR/src/web/static/icons/ 2>/dev/null || true

# 4. Config, Scripts, Root-Dateien
echo "Copying config & scripts..."
scp "$LOCAL_DIR"/config/*.example.json $REMOTE:$REMOTE_DIR/config/
scp "$LOCAL_DIR"/requirements.txt $REMOTE:$REMOTE_DIR/
scp "$LOCAL_DIR"/setup.py $REMOTE:$REMOTE_DIR/
scp "$LOCAL_DIR"/scripts/*.sh "$LOCAL_DIR"/scripts/*.py $REMOTE:$REMOTE_DIR/scripts/
ssh $REMOTE "chmod +x $REMOTE_DIR/scripts/*.sh 2>/dev/null || true"

# 5. Live-State-Files NUR mit --with-config kopieren.
#    Ohne Flag werden diese Files NICHT angefasst — sonst überschreibt der Deploy
#    den Live-Stand auf dem Remote (Trades, Cash-Änderungen, API-Keys).
if [ "$WITH_CONFIG" = "1" ]; then
    if [ -f "$LOCAL_DIR/config/settings.json" ]; then
        echo "Copying settings.json (force)..."
        scp "$LOCAL_DIR"/config/settings.json $REMOTE:$REMOTE_DIR/config/
    fi
    if [ -f "$LOCAL_DIR/config/portfolio.json" ]; then
        echo "Copying portfolio.json (force)..."
        scp "$LOCAL_DIR"/config/portfolio.json $REMOTE:$REMOTE_DIR/config/
    fi
    if [ -f "$LOCAL_DIR/config/watchlist.json" ]; then
        echo "Copying watchlist.json (force)..."
        scp "$LOCAL_DIR"/config/watchlist.json $REMOTE:$REMOTE_DIR/config/
    fi
else
    echo "Skipping live-state files (portfolio/watchlist/settings) — Remote bleibt unverändert."
    echo "  Mit --with-config überschreiben (z.B. für Erst-Setup)."
fi

echo ""
echo "=== Deploy complete ==="
echo "Erst-Installation: ssh $REMOTE 'cd $REMOTE_DIR && python3 setup.py && bash scripts/setup_server.sh'"
echo "Update:            ssh $REMOTE 'sudo systemctl restart velora-web velora-bot'"
