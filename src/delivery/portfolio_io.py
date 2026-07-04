"""Sichere Portfolio-IO: File-Lock + atomic write + rotating Backups.

Verhindert Race-Conditions bei parallelen Trade-Loggings (Web-UI, Telegram,
Chat) und stellt sicher, dass portfolio.json nie durch halbfertige Writes
korrumpiert wird.

Jede Mutation durchläuft `with portfolio_write_lock() as portfolio:` — Block:
1. Lock erwerben (fcntl.flock exklusiv, blockiert andere Writer).
2. Aktuelles File einlesen und zurückgeben.
3. Aufrufer mutiert das Dict.
4. Beim Verlassen: Backup (falls ≥ ~10 Min seit letztem), atomic write.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
BACKUP_DIR = Path(__file__).parent.parent.parent / "memory" / "portfolio_backups"
LOCK_FILE = CONFIG_DIR / ".portfolio.lock"
PORTFOLIO_PATH = CONFIG_DIR / "portfolio.json"

BACKUP_MIN_INTERVAL_SEC = 600  # max 1 Backup pro 10 min (sonst Spam)
BACKUP_KEEP = 60  # etwa 10 Tage bei durchschnittlich 6 Mutationen/Tag


def load_portfolio() -> dict:
    """Einfaches Laden — ohne Lock, für Read-only-Pfade."""
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def _auto_backup() -> None:
    """Rotiert Backups: neue Kopie in memory/portfolio_backups/ wenn letztes älter als BACKUP_MIN_INTERVAL_SEC."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    existing = sorted(BACKUP_DIR.glob("portfolio_*.json"))
    if existing:
        try:
            last_ts = existing[-1].stat().st_mtime
            if now.timestamp() - last_ts < BACKUP_MIN_INTERVAL_SEC:
                return
        except OSError:
            pass
    tag = now.strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"portfolio_{tag}.json"
    try:
        shutil.copy2(PORTFOLIO_PATH, dst)
    except FileNotFoundError:
        return
    # Alte wegrotieren
    for old in existing[:-BACKUP_KEEP + 1]:
        try:
            old.unlink()
        except OSError:
            pass


def _atomic_write(portfolio: dict) -> None:
    """Schreibt portfolio.json atomar (tempfile + os.replace).
    Kein Risiko von halbfertigen Writes bei z.B. Strom-Ausfall / SIGKILL."""
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json.tmp", prefix="portfolio.", dir=str(PORTFOLIO_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Owner + Mode der Original-Datei auf das Tempfile spiegeln, sonst
        # erbt portfolio.json nach jedem root-Write die mkstemp-Defaults
        # (root:root 0600) — und der admin-Cronjob (Briefing) verliert
        # den Lesezugriff.
        _preserve_perms(PORTFOLIO_PATH, tmp_path)
        os.replace(tmp_path, PORTFOLIO_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _preserve_perms(reference: Path, target: str | Path) -> None:
    """Spiegelt Mode (immer) und Owner (nur wenn euid=root) von `reference` auf `target`.
    Schluckt FileNotFoundError für den allerersten Write."""
    try:
        st = os.stat(reference)
    except FileNotFoundError:
        return
    try:
        os.chmod(target, st.st_mode & 0o777)
    except OSError as e:
        logger.warning("chmod auf %s fehlgeschlagen: %s", target, e)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            os.chown(target, st.st_uid, st.st_gid)
        except OSError as e:
            logger.warning("chown auf %s fehlgeschlagen: %s", target, e)


def add_new_position(ticker: str, shares: float, price_eur: float, account: str, trade_currency: str = "EUR") -> bool:
    """Legt eine komplett neue Position an + aktualisiert das Cash-Konto (atomar, mit Lock).

    `price_eur` MUSS schon in EUR sein (Caller konvertiert USD→EUR vorher).
    `trade_currency` beeinflusst nur das buy_in-Feld (Originalwährung), nicht das Cash-Tracking."""
    from datetime import datetime

    # Lokale Imports, um zirkuläre Imports zu vermeiden
    from src.delivery.telegram import update_cash_on_trade

    with portfolio_write_lock() as portfolio:
        if account not in portfolio.get("accounts", {}):
            logger.error("Konto %s existiert nicht in portfolio.json", account)
            return False

        new_pos = {
            "name": ticker,
            "isin": "",
            "ticker": ticker,
            "shares": float(shares),
            "buy_in": float(price_eur),
            "buy_in_eur": float(price_eur),
            "currency": trade_currency or "EUR",
        }
        portfolio["accounts"][account]["positions"].append(new_pos)
        try:
            update_cash_on_trade(portfolio, account, "buy", shares, price_eur)
        except Exception as e:
            logger.warning("Cash-Update fehlgeschlagen bei add_new_position: %s", e)
        portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    logger.info("Neue Position angelegt: %s %s shares=%s @ %s in %s", ticker, trade_currency, shares, price_eur, account)
    return True


class _AbortWrite(Exception):
    """Signalisiert dem Write-Lock, dass NICHT gespeichert werden soll (Validierung fehlgeschlagen)."""

    def __init__(self, error: str):
        super().__init__(error)
        self.error = error


def _find_position(positions: list[dict], ticker: str) -> dict | None:
    """Findet eine Position per Ticker (mit/ohne Exchange-Suffix, case-insensitiv)."""
    t = (ticker or "").upper()
    for pos in positions:
        pt = (pos.get("ticker") or "").upper()
        if pt == t or pt.split(".")[0] == t or t.split(".")[0] == pt:
            return pos
    return None


def edit_position(account: str, ticker: str, updates: dict) -> dict:
    """Korrigiert Felder einer bestehenden Position — REINE Korrektur, KEIN Cash-Effekt.

    `updates` darf enthalten: shares, buy_in, buy_in_eur, currency, name, isin, new_account.
    Cash wird bewusst NICHT angefasst (Korrektur ≠ Trade). Returns {"ok": bool, "error": str}.
    """
    from datetime import datetime
    try:
        with portfolio_write_lock() as portfolio:
            accounts = portfolio.get("accounts", {})
            if account not in accounts:
                raise _AbortWrite(f"Account '{account}' nicht gefunden")
            positions = accounts[account].setdefault("positions", [])
            target = _find_position(positions, ticker)
            if target is None:
                raise _AbortWrite(f"Position {ticker} in {account} nicht gefunden")

            new_account = updates.get("new_account")
            if new_account and new_account != account:
                if new_account not in accounts:
                    raise _AbortWrite(f"Zielaccount '{new_account}' nicht gefunden")
                positions.remove(target)
                accounts[new_account].setdefault("positions", []).append(target)

            for field in ("name", "isin", "currency"):
                if updates.get(field) is not None:
                    target[field] = updates[field]
            if updates.get("shares") is not None:
                target["shares"] = float(updates["shares"])
            if updates.get("buy_in") is not None:
                bi = float(updates["buy_in"])
                target["buy_in"] = bi
                # buy_in_eur nur automatisch mitziehen, wenn Position in EUR notiert.
                if (target.get("currency") or "EUR").upper() == "EUR":
                    target["buy_in_eur"] = bi
            if updates.get("buy_in_eur") is not None:
                target["buy_in_eur"] = float(updates["buy_in_eur"])

            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    logger.info("Position bearbeitet: %s in %s -> %s", ticker, account, updates)
    return {"ok": True}


def delete_position(account: str, ticker: str) -> dict:
    """Entfernt eine Position (Phantom-Korrektur) — KEIN Cash-Effekt."""
    from datetime import datetime
    try:
        with portfolio_write_lock() as portfolio:
            accounts = portfolio.get("accounts", {})
            if account not in accounts:
                raise _AbortWrite(f"Account '{account}' nicht gefunden")
            positions = accounts[account].setdefault("positions", [])
            target = _find_position(positions, ticker)
            if target is None:
                raise _AbortWrite(f"Position {ticker} in {account} nicht gefunden")
            positions.remove(target)
            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    logger.info("Position gelöscht: %s in %s", ticker, account)
    return {"ok": True}


def add_position_correction(account: str, ticker: str, shares: float, buy_in: float,
                            currency: str = "EUR", name: str = "", isin: str = "",
                            buy_in_eur: float | None = None) -> dict:
    """Fügt eine Position manuell hinzu (Bestandskorrektur) — KEIN Cash-Effekt, KEINE yfinance-Prüfung.

    Für den Abgleich mit dem echten Broker-Depot: der Nutzer erfasst, was er bereits besitzt.
    """
    from datetime import datetime
    ticker = (ticker or "").strip().upper()
    try:
        shares = float(shares)
        buy_in = float(buy_in)
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares und buy_in müssen Zahlen sein"}
    if not ticker:
        return {"ok": False, "error": "Ticker fehlt"}
    if shares <= 0 or buy_in <= 0:
        return {"ok": False, "error": "shares und buy_in müssen > 0 sein"}
    currency = (currency or "EUR").upper()
    try:
        with portfolio_write_lock() as portfolio:
            accounts = portfolio.get("accounts", {})
            if account not in accounts:
                raise _AbortWrite(f"Account '{account}' nicht gefunden")
            positions = accounts[account].setdefault("positions", [])
            if _find_position(positions, ticker) is not None:
                raise _AbortWrite(f"Position {ticker} existiert bereits in {account} — bitte bearbeiten statt neu anlegen")
            positions.append({
                "name": name or ticker,
                "isin": isin or "",
                "ticker": ticker,
                "shares": shares,
                "buy_in": buy_in,
                "buy_in_eur": float(buy_in_eur) if buy_in_eur is not None else (buy_in if currency == "EUR" else buy_in),
                "currency": currency,
            })
            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    logger.info("Position manuell erfasst: %s shares=%s @ %s %s in %s", ticker, shares, buy_in, currency, account)
    return {"ok": True}


def edit_bank_account(key: str, updates: dict) -> dict:
    """Korrigiert Felder eines Cash-/Bank-Kontos (value, interest, note, bank, is_depot_cash).

    Reine Bestandskorrektur — Kontostände ändern sich laufend (Gehalt, Zinsen,
    Ausgaben), das hier ist der Abgleich mit der Realität. Kein Trade-Effekt.
    """
    from datetime import datetime
    try:
        with portfolio_write_lock() as portfolio:
            banks = portfolio.setdefault("bank_accounts", {})
            if key not in banks:
                raise _AbortWrite(f"Konto '{key}' nicht gefunden")
            acc = banks[key]
            if updates.get("value") is not None:
                acc["value"] = round(float(updates["value"]), 2)
            if updates.get("interest") is not None:
                acc["interest"] = float(updates["interest"])
            if updates.get("note") is not None:
                acc["note"] = updates["note"]
            if updates.get("bank") is not None:
                acc["bank"] = updates["bank"]
            if updates.get("is_depot_cash") is not None:
                acc["is_depot_cash"] = bool(updates["is_depot_cash"])
            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    except (TypeError, ValueError):
        return {"ok": False, "error": "value und interest müssen Zahlen sein"}
    logger.info("Bank-Konto bearbeitet: %s -> %s", key, updates)
    return {"ok": True}


def add_bank_account(key: str, bank: str, value, interest=0.0, note: str = "",
                     is_depot_cash: bool = False) -> dict:
    """Legt ein neues Cash-/Bank-Konto an (z.B. neues Tagesgeld-Konto)."""
    from datetime import datetime
    key = (key or "").strip().lower().replace(" ", "_")
    if not key:
        return {"ok": False, "error": "Konto-Name fehlt"}
    try:
        value = round(float(value), 2)
        interest = float(interest or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "value und interest müssen Zahlen sein"}
    if value < 0:
        return {"ok": False, "error": "value darf nicht negativ sein"}
    try:
        with portfolio_write_lock() as portfolio:
            banks = portfolio.setdefault("bank_accounts", {})
            if key in banks:
                raise _AbortWrite(f"Konto '{key}' existiert bereits — bitte bearbeiten")
            banks[key] = {"bank": bank or key, "value": value, "interest": interest,
                          "note": note or "", "is_depot_cash": bool(is_depot_cash)}
            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    logger.info("Bank-Konto angelegt: %s (%s, %.2f EUR)", key, bank, value)
    return {"ok": True}


def delete_bank_account(key: str) -> dict:
    """Entfernt ein Cash-/Bank-Konto (z.B. aufgelöstes Tagesgeld).

    Achtung: Depot-Cash-Konten (is_depot_cash) sind Ziel des automatischen
    Cash-Trackings bei Trades (ACCOUNT_CASH_MAP) — Löschen deaktiviert dieses
    Tracking still. Der Aufrufer (UI) soll davor warnen.
    """
    from datetime import datetime
    try:
        with portfolio_write_lock() as portfolio:
            banks = portfolio.setdefault("bank_accounts", {})
            if key not in banks:
                raise _AbortWrite(f"Konto '{key}' nicht gefunden")
            del banks[key]
            portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    except _AbortWrite as e:
        return {"ok": False, "error": e.error}
    logger.info("Bank-Konto gelöscht: %s", key)
    return {"ok": True}


@contextlib.contextmanager
def portfolio_write_lock():
    """Context-Manager: Lock, Load, (Mutate), Backup, Atomic-Save, Unlock.

    Nutzung:
        with portfolio_write_lock() as portfolio:
            portfolio["accounts"][...]["positions"].append(...)
        # Beim Verlassen: atomisch gespeichert.

    Wenn eine Exception im Block geworfen wird, wird nicht gespeichert.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Lock-File offen halten — fcntl.flock ist an Filedescriptor gebunden.
    # O_RDWR|O_CREAT statt "w": kein Truncate, damit ein als-root erstelltes
    # Lock-File später auch von admin-Prozessen (Cronjob) wieder geöffnet
    # werden kann, ohne dass jeder Aufruf Owner/Mode überschreibt.
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o664)
    with os.fdopen(fd, "r+") as lockfile:
        try:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
        except OSError as e:
            logger.warning("Portfolio-Lock konnte nicht erworben werden: %s — trotzdem weitermachen", e)

        try:
            with open(PORTFOLIO_PATH) as f:
                portfolio = json.load(f)
        except Exception as e:
            logger.error("portfolio.json konnte nicht geladen werden: %s", e)
            raise

        try:
            yield portfolio
            _auto_backup()
            _atomic_write(portfolio)
        finally:
            try:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
