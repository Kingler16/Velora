#!/bin/bash
# Velora — Server-Setup (Raspberry Pi, Mini-PC, VPS … mit systemd)
#
#   bash scripts/setup_server.sh [install-dir]
#
# Vorher einmal `python3 setup.py` ausführen (Konfiguration + venv). Das Skript ist
# idempotent und kann nach Änderungen (z. B. Telegram nachträglich eingerichtet)
# erneut laufen. Es richtet ein:
#   - velora-web            Web-Dashboard + API für die iOS-App (immer)
#   - velora-bot            Telegram-Bot (nur wenn telegram.bot_token gesetzt ist)
#   - velora-auth-watchdog  täglicher Test, ob der Claude-Login noch gilt (Timer)
#   - Cron-Jobs für Briefings (Zeitplan aus settings.json, später in App/Web änderbar)
#     und Monatsreport
set -e

INSTALL_DIR="$(cd "${1:-$(dirname "$0")/..}" && pwd)"
RUN_USER="$(whoami)"
RUN_HOME="$HOME"
PY="$INSTALL_DIR/venv/bin/python"

echo "=== Velora Server Setup ($INSTALL_DIR, User $RUN_USER) ==="

# 1. System-Pakete + Claude Code CLI
if command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y python3-pip python3-venv nodejs npm
fi
command -v claude >/dev/null 2>&1 || sudo npm install -g @anthropic-ai/claude-code || echo "Claude CLI install failed — install manually"

# 2. Python venv
cd "$INSTALL_DIR"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --prefer-binary -q -r requirements.txt
mkdir -p "$INSTALL_DIR/logs"

if [ ! -f config/settings.json ]; then
    echo "config/settings.json fehlt — zuerst 'python3 setup.py' ausführen."
    exit 1
fi

setting() {  # setting <abschnitt> <schlüssel> → Wert aus settings.json (leer wenn nicht gesetzt)
    "$PY" -c "import json,sys; s=json.load(open('config/settings.json')); v=s.get(sys.argv[1],{}).get(sys.argv[2],''); print(','.join(v) if isinstance(v,list) else v)" "$1" "$2"
}

# 3. Cron: Briefings nach Zeitplan aus settings.json (src/briefing_cron.py – dieselbe Logik,
#    mit der App und Web den Zeitplan später ändern), Monatsreport am 1. um 9:00
( crontab -l 2>/dev/null | grep -v "src.main monthly\|# Velora — Monatsreport" ; cat <<CRON
# Velora — Monatsreport am 1. um 9:00
0 9 1 * * cd $INSTALL_DIR && ./venv/bin/python -m src.main monthly >> $INSTALL_DIR/logs/monthly.log 2>&1
CRON
) | crontab -
"$PY" -m src.briefing_cron

# 4. systemd-Dienste. HOME zeigt auf den Benutzer, weil die Claude-CLI ihren Login
#    unter \$HOME/.claude sucht.
unit() {  # unit <name> <beschreibung> <modus>
    sudo tee "/etc/systemd/system/$1.service" > /dev/null <<SERVICE
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Environment=HOME=$RUN_HOME
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=-$INSTALL_DIR/.env
ExecStart=$PY -m src.main $3
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE
}

unit velora-web "Velora Web Dashboard + App API" web
if [ -n "$(setting telegram bot_token)" ] && [ -n "$(setting telegram chat_id)" ]; then
    unit velora-bot "Velora Telegram Bot" bot
    BOT=1
else
    BOT=
fi

sudo tee /etc/systemd/system/velora-auth-watchdog.service > /dev/null <<SERVICE
[Unit]
Description=Velora: Claude-Login prüfen (Mitteilung bei Fehler)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$RUN_USER
Environment=HOME=$RUN_HOME
WorkingDirectory=$INSTALL_DIR
ExecStart=$PY $INSTALL_DIR/scripts/auth_watchdog.py
SERVICE
sudo tee /etc/systemd/system/velora-auth-watchdog.timer > /dev/null <<TIMER
[Unit]
Description=Velora: Claude-Login täglich vor dem Briefing prüfen

[Timer]
OnCalendar=*-*-* 06:30:00
OnBootSec=5min
RandomizedDelaySec=3min
Persistent=true

[Install]
WantedBy=timers.target
TIMER

sudo systemctl daemon-reload
sudo systemctl enable --now velora-web velora-auth-watchdog.timer
sudo systemctl restart velora-web
if [ -n "$BOT" ]; then
    sudo systemctl enable --now velora-bot
    sudo systemctl restart velora-bot
    echo "✓ Telegram-Bot läuft"
elif [ -f /etc/systemd/system/velora-bot.service ]; then
    sudo systemctl disable --now velora-bot 2>/dev/null || true
    echo "• Telegram nicht konfiguriert — velora-bot ist aus"
fi

echo ""
echo "=== Setup complete ==="
echo "1. Claude einloggen (einmalig): claude setup-token, dann ./venv/bin/python scripts/set_oauth_token.py"
echo "2. Test: ./venv/bin/python -m src.main briefing"
echo "3. Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
