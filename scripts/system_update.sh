#!/bin/bash
# Velora self-update via git pull. Called by /api/system/update.
# Outputs a single JSON line on success, or {"error": "..."} on failure.
# Does NOT restart services — the Python endpoint schedules that separately
# so the HTTP response can return before the service is killed.

set -e

REPO_DIR="${VELORA_REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR" 2>/dev/null || { echo '{"error":"repo_dir_missing"}'; exit 1; }

if ! command -v git >/dev/null 2>&1; then
    echo '{"error":"git_not_installed"}'; exit 1
fi

if [ ! -d .git ]; then
    echo '{"error":"not_a_git_repo"}'; exit 1
fi

# Git operations run inside the service process (often as root).
# safe.directory handles the "dubious ownership" warning.
git config --global --add safe.directory "$REPO_DIR" 2>/dev/null || true

BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# Fetch. Errors here mean no network / auth / remote missing — report them.
if ! FETCH_ERR=$(git fetch origin main 2>&1); then
    printf '{"error":"fetch_failed","detail":%s}\n' "$(printf '%s' "$FETCH_ERR" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()[:400]))')"
    exit 1
fi

# Hard reset to origin/main. Files in .gitignore (portfolio.json, settings.json,
# watchlist.json, memory/, logs/, venv/) stay untouched — git only touches
# tracked files.
if ! RESET_ERR=$(git reset --hard origin/main 2>&1); then
    printf '{"error":"reset_failed","detail":%s}\n' "$(printf '%s' "$RESET_ERR" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()[:400]))')"
    exit 1
fi

AFTER=$(git rev-parse HEAD)
SUBJECT=$(git log -1 --format=%s | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()[:160]))')
CHANGED="false"
[ "$BEFORE" != "$AFTER" ] && CHANGED="true"

# Own everything back to admin so non-root users can inspect/edit later.
chown -R admin:admin "$REPO_DIR" 2>/dev/null || true

printf '{"status":"ok","before":"%s","after":"%s","changed":%s,"subject":%s}\n' \
    "$BEFORE" "$AFTER" "$CHANGED" "$SUBJECT"
