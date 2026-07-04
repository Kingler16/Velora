"""Einmal-Reparatur: fehlendes buy_in_eur aus handerfassten EUR-Buy-ins setzen.

Kontext: Positionen wurden beim Einrichten mit Buy-in-Werten in EUR erfasst,
tragen aber currency=USD (die Notierungswährung des Tickers). Ohne
buy_in_eur-Feld leitet Velora den EUR-Einstand per buy_in / EUR-USD-Kurs ab —
der ohnehin schon in EUR erfasste Wert wird also nochmal durch den Dollarkurs
geteilt. Folge: Einstand ~8% zu niedrig, Rendite ~8 Prozentpunkte zu hoch
("passt ungefähr, aber nicht zu 100%").

Annahme dieses Scripts (Erfassungs-Konvention des Nutzers):
    Jeder buy_in OHNE buy_in_eur wurde in EUR eingegeben -> buy_in_eur = buy_in.

Positionen, die buy_in_eur bereits haben (z.B. über den Trade-Pfad angelegt),
werden NICHT angefasst. Das currency-Feld bleibt ebenfalls unangetastet — es
dient nach dem FX-Fix (resolve_quote_currency) nur noch als Fallback für die
Live-Kurs-Währung, und dafür ist die Ticker-Notierung (USD) korrekt.

Nutzung (am Gerät mit dem echten Portfolio):
    venv/bin/python scripts/repair_buyin_eur.py            # Dry-Run (zeigt nur)
    venv/bin/python scripts/repair_buyin_eur.py --apply    # schreibt (Lock+Backup)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.delivery.portfolio_io import load_portfolio, portfolio_write_lock  # noqa: E402


def find_candidates(portfolio: dict) -> list[dict]:
    out = []
    for account_name, account in portfolio.get("accounts", {}).items():
        for pos in account.get("positions", []):
            if pos.get("buy_in_eur"):
                continue  # schon vorhanden — vertrauenswürdig, nicht anfassen
            buy_in = pos.get("buy_in")
            if not buy_in:
                continue
            out.append({
                "account": account_name,
                "ticker": pos.get("ticker", "?"),
                "currency": pos.get("currency", "EUR"),
                "buy_in": buy_in,
            })
    return out


def main() -> int:
    apply = "--apply" in sys.argv

    candidates = find_candidates(load_portfolio())
    if not candidates:
        print("Nichts zu reparieren — alle Positionen haben bereits buy_in_eur.")
        return 0

    print(f"{'ACCOUNT':18s} {'TICKER':10s} {'CCY':4s} {'buy_in':>10s}  -> buy_in_eur")
    print("-" * 60)
    for c in candidates:
        marker = "  <- Reparatur relevant (war: buy_in/FX)" if c["currency"] != "EUR" else ""
        print(f"{c['account']:18s} {c['ticker']:10s} {c['currency']:4s} {c['buy_in']:>10.2f}  -> {c['buy_in']:.2f} €{marker}")
    print("-" * 60)
    print(f"{len(candidates)} Position(en) ohne buy_in_eur. Annahme: buy_in wurde in EUR erfasst.")

    if not apply:
        print("\nDRY-RUN — nichts geschrieben. Mit --apply ausführen, wenn die Liste stimmt.")
        return 0

    fixed = 0
    with portfolio_write_lock() as portfolio:
        for account in portfolio.get("accounts", {}).values():
            for pos in account.get("positions", []):
                if pos.get("buy_in_eur") or not pos.get("buy_in"):
                    continue
                pos["buy_in_eur"] = float(pos["buy_in"])
                fixed += 1
    print(f"\n{fixed} Position(en) repariert (buy_in_eur gesetzt). Backup liegt in memory/portfolio_backups/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
