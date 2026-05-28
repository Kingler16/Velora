#!/bin/bash
# claude_keepalive.sh — hält den Claude-CLI-OAuth-Token warm.
#
# Ruft Claude CLI mit einem trivialen Prompt auf, damit der Refresh-Token
# aktiv genutzt wird und ein neuer Access-Token ausgestellt wird bevor der
# alte abläuft. Verhindert dass das Token nach mehreren inaktiven Tagen
# invalidiert wird.
#
# Nutzt den gleichen flock wie ask_claude() in src/analysis/claude.py —
# so gibt es keine Race Condition mit parallel laufendem Briefing/Chat,
# die .credentials.json korrumpieren könnte.
#
# Installation als systemd-Timer: siehe scripts/systemd/

set -u

CLAUDE_BIN="${CLAUDE_BIN:-/usr/local/bin/claude}"
export HOME="${HOME:-/home/admin}"

LOCK_FILE="$HOME/.claude/.velora-cli.lock"
mkdir -p "$(dirname "$LOCK_FILE")"

# flock mit 300s Timeout — wenn gerade ein Briefing läuft, warten wir.
exec 9>"$LOCK_FILE"
if ! flock -x -w 300 9; then
    echo "[keepalive] konnte kein Lock bekommen nach 300s — abgebrochen" >&2
    exit 1
fi

# Trivialer Call — refresht den Access-Token via Refresh-Token.
OUTPUT=$("$CLAUDE_BIN" --print \
    --tools "" \
    --no-session-persistence \
    --model claude-opus-4-8 \
    --effort low \
    "ok" 2>&1)
EXIT=$?

if [ $EXIT -ne 0 ]; then
    echo "[keepalive] Claude CLI exit $EXIT:" >&2
    echo "$OUTPUT" >&2
    exit $EXIT
fi

echo "[keepalive] ok ($(date -Iseconds))"
