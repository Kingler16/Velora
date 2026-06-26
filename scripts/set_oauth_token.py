#!/usr/bin/env python3
"""
Hinterlegt den langlebigen Claude-OAuth-Token (aus `claude setup-token`) sicher
in config/settings.json unter claude.oauth_token.

Liest den Token via getpass — er erscheint NICHT in der Shell-History, NICHT in der
Prozessliste (argv) und NICHT als Terminal-Echo. Schreibt atomar, damit ein
Abbruch settings.json nie halb beschreibt.

Nutzung am RockPi:
    cd /home/admin/velora
    claude setup-token                            # Token erzeugen + kopieren
    ./venv/bin/python scripts/set_oauth_token.py  # Token einfügen, Enter
    sudo systemctl restart velora-web velora-bot
"""

import getpass
import json
import sys
from pathlib import Path

_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def main() -> int:
    if not _SETTINGS.exists():
        print(f"settings.json nicht gefunden: {_SETTINGS}", file=sys.stderr)
        return 1

    try:
        token = getpass.getpass("Claude OAuth-Token (Eingabe verborgen): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen.", file=sys.stderr)
        return 1

    if not token:
        print("Kein Token eingegeben — abgebrochen (nichts geändert).", file=sys.stderr)
        return 1
    if len(token) < 20:
        print("Token wirkt zu kurz — abgebrochen (nichts geändert).", file=sys.stderr)
        return 1

    data = json.loads(_SETTINGS.read_text())
    data.setdefault("claude", {})["oauth_token"] = token

    tmp = _SETTINGS.with_name(_SETTINGS.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(_SETTINGS)

    masked = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
    print(f"OK — claude.oauth_token gesetzt ({masked}).")
    print("Jetzt neustarten:  sudo systemctl restart velora-web velora-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
