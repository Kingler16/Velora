"""Empfehlungsverlauf zurücksetzen — Neustart für die Empfehlungs-Bilanz.

Kontext: Vor dem Order-Tracking wurden platzierte (aber nie gefüllte)
Limit-Orders als ausgeführt gewertet und Phantom-Positionen gebucht. Die
daraus entstandene Empfehlungs-Historie (Hit-Rate, Expectancy, Outcomes in
memory/recommendations.json) ist damit nicht aussagekräftig. Dieses Script
archiviert sie und beginnt bei null.

Was es tut:
  - memory/recommendations.json -> memory/recommendations_archive_<ts>.json
  - schreibt eine leere Liste als neuen Verlauf

Was es NICHT anfasst: orders.json (neues, korrektes System), Briefings,
Trade-History, Positions-Thesen, Portfolio.

Nutzung (am Gerät mit den echten Daten):
    venv/bin/python scripts/reset_recommendations.py            # Dry-Run
    venv/bin/python scripts/reset_recommendations.py --apply    # archiviert + leert
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path(__file__).parent.parent / "memory"
RECS_PATH = MEMORY_DIR / "recommendations.json"


def main() -> int:
    apply = "--apply" in sys.argv

    if not RECS_PATH.exists():
        print("Kein Empfehlungsverlauf vorhanden (memory/recommendations.json fehlt) — nichts zu tun.")
        return 0

    try:
        with open(RECS_PATH) as f:
            recs = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"recommendations.json nicht lesbar: {e}")
        return 1

    if not recs:
        print("Empfehlungsverlauf ist bereits leer — nichts zu tun.")
        return 0

    by_status = Counter(r.get("status", "?") for r in recs)
    print(f"{len(recs)} Empfehlung(en) im Verlauf:")
    for status, n in by_status.most_common():
        print(f"  {status:14s} {n}")

    if not apply:
        print("\nDRY-RUN — nichts geändert. Mit --apply wird der Verlauf archiviert und geleert.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = MEMORY_DIR / f"recommendations_archive_{ts}.json"
    archive.write_text(json.dumps(recs, indent=2, ensure_ascii=False))

    tmp = RECS_PATH.with_suffix(".json.tmp")
    tmp.write_text("[]")
    tmp.replace(RECS_PATH)

    print(f"\nVerlauf archiviert nach {archive.name} und geleert.")
    print("Hit-Rate/Empfehlungs-Bilanz starten bei null — ab jetzt zählt nur der Order-Tracking-Flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
