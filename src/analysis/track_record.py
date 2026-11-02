"""
Ehrliche Erfolgsbilanz des Beraters (Messfundament).

recommendations.json bleibt der Arbeitsspeicher für UI und Orders. Hier liegt das
Archiv zum Lernen und Messen, und zwar so, dass es nichts verliert:

- Jede angenommene Empfehlung wird ANGEHÄNGT, nie überschrieben. Kommt für denselben
  Ticker eine neue, wird die alte sauber geschlossen (Status "superseded", mit Rendite).
- Beim Einstieg werden Benchmark-Stand (MSCI World in EUR), Marktregime und EUR/USD
  gespeichert → Überrendite (Alpha) je Empfehlung statt nackter Trefferquote.
- Bewertet wird über Tageshoch/-tief (OHLC), nicht über einen Momentkurs zum
  Briefing-Zeitpunkt: Limits zählen erst, wenn der Kurs sie berührt hat, Stops und
  Ziele werden auch zwischen zwei Briefings erkannt. Ohne Ausstieg wird nach 365
  Tagen zum Marktpreis geschlossen.
- "hold" (Stop nachziehen) ist keine Anlageidee und zählt nicht in die Trefferquote.
  Stattdessen wird gemessen, was ein ausgelöster Stop gekostet hat (Kurs 30/90 Tage
  danach).
- Schattenbuch der abgelehnten Kandidaten: Screener- und Watchlist-Titel, die im
  Briefing NICHT empfohlen wurden, werden mitverfolgt. So wird sichtbar, was
  Nichtstun kostet.
- Tägliche Depot-NAV mit zeitgewichteter Rendite (TWR), unabhängig von Käufen,
  Verkäufen und Einzahlungen.

Speicher: memory/track_record.db (gitignored). Schema nur additiv.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
DB_PATH = MEMORY_DIR / "track_record.db"

# MSCI World in EUR (iShares Core MSCI World, Xetra) — der Vergleichsmaßstab für alles.
BENCHMARK_TICKER = "EUNL.DE"
BENCHMARK_NAME = "MSCI World (EUR)"

HORIZON_DAYS = 365          # danach Bewertung zum Marktpreis
LIMIT_EXPIRE_DAYS = 30      # unberührte Limit-Kaufideen verfallen
MTM_MARKS = (90, 180, 365)  # Zwischenstände ab Einstieg
POST_STOP_MARKS = (30, 90)  # Kursverlauf nach ausgelöstem Stop
CANDIDATE_MARKS = (30, 90, 180)
CANDIDATE_DEDUPE_DAYS = 30  # derselbe abgelehnte Titel zählt höchstens einmal pro 30 Tage
LIMIT_TOLERANCE = 0.01      # Einstieg >1 % unter Kurs = Limit-Order
MIN_SIGNAL_N = 20           # darunter ist eine Trefferquote Rauschen

TRADE_CLOSED = ("target_hit", "stop_hit", "horizon", "superseded")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    briefing_id INTEGER,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    category TEXT NOT NULL,          -- trade | stop
    entry_price REAL, target_price REAL, stop_loss REAL,
    shares REAL, sell_pct REAL,
    reasoning TEXT,
    currency TEXT,
    ref_price REAL,                  -- Kurs beim Anlegen
    fx_eur_usd REAL,                 -- EUR/USD beim Anlegen
    bench_level REAL,                -- Benchmark-Schluss beim Anlegen
    regime TEXT,
    status TEXT NOT NULL,            -- pending | open | target_hit | stop_hit | horizon | superseded | expired | tracking | stop_triggered | done
    filled_at TEXT, fill_price REAL, fill_bench REAL, fill_fx REAL,
    closed_at TEXT, exit_price REAL, exit_bench REAL, exit_fx REAL,
    return_pct REAL,                 -- in EUR, bei sell mit umgekehrtem Vorzeichen
    bench_return_pct REAL,
    alpha_pct REAL,
    marks TEXT,                      -- JSON {"90": {"return_pct":..,"alpha_pct":..}, ...}
    superseded_at TEXT,              -- ab hier gilt eine neuere Empfehlung zum selben Ticker
    source TEXT DEFAULT 'briefing',  -- briefing | backfill
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_ticker ON recommendations(ticker, status);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    briefing_id INTEGER,
    ticker TEXT NOT NULL,
    origin TEXT,                     -- screener | watchlist
    currency TEXT,
    ref_price REAL, fx_eur_usd REAL, bench_level REAL,
    marks TEXT,
    done INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cand_ticker ON candidates(ticker, created_at);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    regime TEXT,
    n_accepted INTEGER, n_dropped INTEGER,
    dropped TEXT,                    -- JSON [{ticker, reason}]
    snapshot_path TEXT
);

CREATE TABLE IF NOT EXISTS nav_daily (
    date TEXT PRIMARY KEY,
    holdings_eur REAL, cash_eur REAL, total_eur REAL,
    positions TEXT,                  -- JSON {ticker: {"shares":..,"price_eur":..}}
    twr_factor REAL,                 -- verketteter Depot-Faktor seit erster Messung
    bench_level REAL,
    recorded_at TEXT
);
"""


# ─── Infrastruktur ───────────────────────────────────────────

@contextmanager
def _db():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> datetime:
    return datetime.now()


def _finite(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _lookup(market_data: dict | None, ticker: str) -> dict:
    md = market_data or {}
    pos = (md.get("positions") or {}).get(ticker) or (md.get("watchlist") or {}).get(ticker)
    return (pos or {}).get("price") or {}


def _eur_usd(market_data: dict | None):
    try:
        return _finite(((market_data or {}).get("indices") or {}).get("EUR/USD", {}).get("value"))
    except AttributeError:
        return None


def _to_eur(price, currency, fx):
    """Kurs in EUR. Nur USD wird umgerechnet; andere Währungen bleiben lokal."""
    if price is None:
        return None
    if currency == "USD" and fx:
        return price / fx
    return price


# ─── Kursdaten (yfinance, im Test ersetzbar) ─────────────────

def fetch_daily_bars(ticker: str, start: date) -> list[dict]:
    """Tages-OHLC ab `start` (unbereinigt, damit Stop-/Ziel-Level vergleichbar bleiben)."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=False)
    except Exception as e:
        logger.warning("Kurshistorie %s nicht verfügbar: %s", ticker, e)
        return []
    bars = []
    if hist is None or hist.empty:
        return bars
    for idx, row in hist.iterrows():
        o, h, l, c = (_finite(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        if c is None:
            continue
        bars.append({"date": idx.date().isoformat(), "open": o or c, "high": h or c,
                     "low": l or c, "close": c})
    return bars


class _BarCache:
    """Pro Bewertungslauf jede Historie nur einmal laden."""

    def __init__(self, fetch=None):
        self._fetch = fetch or fetch_daily_bars
        self._data: dict[str, tuple[date, list[dict]]] = {}

    def bars(self, ticker: str, start: date) -> list[dict]:
        have = self._data.get(ticker)
        if have is None or start < have[0]:
            self._data[ticker] = (start, self._fetch(ticker, start - timedelta(days=7)))
        return [b for b in self._data[ticker][1] if b["date"] >= start.isoformat()]

    def close_on(self, ticker: str, day: date):
        """Letzter Schlusskurs an oder vor `day`."""
        best = None
        for b in self.bars(ticker, day - timedelta(days=10)):
            if b["date"] <= day.isoformat():
                best = b["close"]
        return best


def _bench(market_data: dict | None):
    """Benchmark-Stand aus den Marktdaten (Index-Liste), sonst None."""
    try:
        return _finite(((market_data or {}).get("indices") or {}).get(BENCHMARK_NAME, {}).get("value"))
    except AttributeError:
        return None


# ─── Erfassen ────────────────────────────────────────────────

def record_briefing(accepted: list[dict], dropped: list[dict] | None, market_data: dict | None,
                    regime: dict | None = None, candidates: list[dict] | None = None,
                    snapshot_path: str | None = None, now: datetime | None = None) -> int | None:
    """Archiviert die Empfehlungen und abgelehnten Kandidaten eines Briefings.

    Best-effort: ein Fehler hier darf das Briefing nie abbrechen."""
    try:
        now = now or _now()
        regime_label = (regime or {}).get("label")
        fx = _eur_usd(market_data)
        bench = _bench(market_data)
        if bench is None:
            bench = _BarCache().close_on(BENCHMARK_TICKER, now.date())
        with _db() as conn:
            cur = conn.execute(
                "INSERT INTO briefings (created_at, regime, n_accepted, n_dropped, dropped, snapshot_path) "
                "VALUES (?,?,?,?,?,?)",
                (now.isoformat(), regime_label, len(accepted), len(dropped or []),
                 json.dumps(dropped or [], ensure_ascii=False), snapshot_path),
            )
            briefing_id = cur.lastrowid
            # Screener-Titel stehen nicht in market_data — für den Einstiegskurs mitnachschlagen.
            lookup = dict(market_data or {})
            lookup["watchlist"] = {**{c["ticker"]: c for c in (candidates or []) if c.get("ticker")},
                                   **((market_data or {}).get("watchlist") or {})}
            for rec in accepted:
                _insert_rec(conn, rec, briefing_id, lookup, fx, bench, regime_label, now)
            recommended = {(r.get("ticker") or "").upper() for r in accepted}
            # Laufende Kaufideen sind keine Ablehnung, auch wenn sie diesmal nicht neu genannt werden.
            recommended |= {r["ticker"].upper() for r in conn.execute(
                "SELECT ticker FROM recommendations WHERE category='trade' AND status IN ('pending','open')")}
            held = {t.upper() for t in ((market_data or {}).get("positions") or {})}
            _record_candidates(conn, candidates, market_data, recommended | held, briefing_id, fx, bench, now)
        return briefing_id
    except Exception:
        logger.exception("Track-Record: Briefing konnte nicht archiviert werden")
        return None


def _insert_rec(conn, rec, briefing_id, market_data, fx, bench, regime_label, now, source="briefing"):
    ticker = (rec.get("ticker") or "").strip()
    action = rec.get("action")
    if not ticker or action not in ("buy", "sell", "watch", "hold"):
        return None
    category = "stop" if action == "hold" else "trade"
    price = _lookup(market_data, ticker)
    ref = _finite(price.get("current_price")) or _finite(rec.get("ref_price"))
    currency = price.get("currency") or rec.get("currency")

    # Offene Vorgänger derselben Kategorie nicht überschreiben, sondern mit Enddatum
    # versehen. Die Bewertung schließt sie dann zum Kurs vor diesem Tag ("superseded").
    conn.execute(
        "UPDATE recommendations SET superseded_at=? WHERE ticker=? AND category=? "
        "AND status IN ('pending','open','tracking') AND superseded_at IS NULL",
        (now.isoformat(), ticker, category),
    )

    status = "tracking" if category == "stop" else "pending"
    cur = conn.execute(
        "INSERT INTO recommendations (created_at, briefing_id, ticker, action, category, entry_price, "
        "target_price, stop_loss, shares, sell_pct, reasoning, currency, ref_price, fx_eur_usd, "
        "bench_level, regime, status, marks, source, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(rec.get("date") or now.isoformat()), briefing_id, ticker, action, category,
         _finite(rec.get("entry_price")), _finite(rec.get("target_price")), _finite(rec.get("stop_loss")),
         _finite(rec.get("shares")), _finite(rec.get("sell_pct")), rec.get("reasoning"),
         currency, ref, fx, bench, regime_label, status, "{}", source,
         json.dumps(rec, ensure_ascii=False, default=str)),
    )
    return cur.lastrowid


def _record_candidates(conn, candidates, market_data, exclude, briefing_id, fx, bench, now):
    pool = []
    for c in candidates or []:
        t = c.get("ticker")
        if t:
            pool.append((t, "screener", c.get("price") or c))
    for t, item in ((market_data or {}).get("watchlist") or {}).items():
        pool.append((t, "watchlist", item.get("price") or {}))
    cutoff = (now - timedelta(days=CANDIDATE_DEDUPE_DAYS)).isoformat()
    seen = set()
    for ticker, origin, price in pool:
        key = ticker.upper()
        if key in exclude or key in seen:
            continue
        seen.add(key)
        ref = _finite(price.get("current_price"))
        if ref is None:
            continue
        if conn.execute("SELECT 1 FROM candidates WHERE ticker=? AND created_at>=?", (ticker, cutoff)).fetchone():
            continue
        conn.execute(
            "INSERT INTO candidates (created_at, briefing_id, ticker, origin, currency, ref_price, "
            "fx_eur_usd, bench_level, marks) VALUES (?,?,?,?,?,?,?,?,?)",
            (now.isoformat(), briefing_id, ticker, origin, price.get("currency"), ref, fx, bench, "{}"),
        )


def ensure_backfilled(recs: list[dict], fetch=None) -> int:
    """Beim ersten Lauf die Alt-Empfehlungen übernehmen (danach No-op)."""
    try:
        with _db() as conn:
            if conn.execute("SELECT 1 FROM recommendations LIMIT 1").fetchone():
                return 0
        return backfill_from_json(recs, fetch) if recs else 0
    except Exception:
        logger.exception("Track-Record: Backfill fehlgeschlagen")
        return 0


def backfill_from_json(recs: list[dict], fetch=None) -> int:
    """Übernimmt Alt-Empfehlungen aus recommendations.json einmalig ins Archiv.

    Benchmark- und Wechselkursstand am Anlegetag werden aus der Kurshistorie
    nachgeschlagen. Schon vorhandene (Ticker + Anlagedatum) werden übersprungen."""
    cache = _BarCache(fetch)
    added = 0
    with _db() as conn:
        for rec in sorted(recs or [], key=lambda r: str(r.get("date") or "")):
            created = str(rec.get("date") or "")
            ticker = rec.get("ticker")
            if not created or not ticker:
                continue
            if conn.execute("SELECT 1 FROM recommendations WHERE ticker=? AND created_at=?",
                            (ticker, created)).fetchone():
                continue
            try:
                day = datetime.fromisoformat(created[:19]).date()
            except ValueError:
                continue
            bench = cache.close_on(BENCHMARK_TICKER, day)
            fx = cache.close_on("EURUSD=X", day)
            ref = cache.close_on(ticker, day) or _finite(rec.get("entry_price"))
            md = {"positions": {ticker: {"price": {"current_price": ref, "currency": _guess_currency(ticker)}}}}
            ts = datetime.fromisoformat(created[:19])
            if _insert_rec(conn, rec, None, md, fx, bench, None, ts, source="backfill"):
                added += 1
    if added:
        logger.info("Track-Record: %d Alt-Empfehlungen übernommen", added)
    return added


def _guess_currency(ticker: str) -> str:
    """Grobe Währung aus dem Börsenkürzel (nur für den Backfill ohne Marktdaten)."""
    if "." not in ticker:
        return "USD"
    suffix = ticker.rsplit(".", 1)[1].upper()
    return {"L": "GBp", "SW": "CHF", "TO": "CAD", "HK": "HKD", "T": "JPY"}.get(suffix, "EUR")


# ─── Bewerten ────────────────────────────────────────────────

def _returns(row, exit_price, exit_fx, exit_bench, fill_price=None, fill_fx=None, fill_bench=None):
    """(Rendite %, Benchmark-Rendite %, Alpha %) in EUR. sell = umgekehrtes Vorzeichen."""
    keys = row.keys() if hasattr(row, "keys") else row
    fill_price = fill_price if fill_price is not None else row["fill_price"] or row["ref_price"]
    fill_fx = fill_fx if fill_fx is not None else (row["fill_fx"] if "fill_fx" in keys else None) or row["fx_eur_usd"]
    fill_bench = fill_bench if fill_bench is not None else (row["fill_bench"] if "fill_bench" in keys else None) or row["bench_level"]
    cur = row["currency"]
    a = _to_eur(fill_price, cur, fill_fx)
    b = _to_eur(exit_price, cur, exit_fx or fill_fx)
    if not a or b is None:
        return None, None, None
    ret = (b / a - 1) * 100
    if row["action"] == "sell":
        ret = -ret
    bret = ((exit_bench / fill_bench - 1) * 100) if exit_bench and fill_bench else None
    if bret is not None and row["action"] == "sell":
        # Ein Verkauf ist richtig, wenn der Titel schlechter lief als der Markt.
        bret = -bret
    alpha = (ret - bret) if bret is not None else None
    r2 = lambda x: round(x, 2) if x is not None else None
    return r2(ret), r2(bret), r2(alpha)


def evaluate_open(today: date | None = None, fetch=None) -> dict:
    """Bewertet alle laufenden Einträge anhand der Tageskurse seit dem Anlegen."""
    today = today or date.today()
    cache = _BarCache(fetch)
    stats = {"filled": 0, "closed": 0, "expired": 0, "stops": 0, "candidates": 0}
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM recommendations WHERE status IN ('pending','open','tracking','stop_triggered')"
            ).fetchall()
            for row in rows:
                if row["category"] == "trade":
                    _evaluate_trade(conn, row, cache, today, stats)
                else:
                    _evaluate_stop(conn, row, cache, today, stats)
            for row in conn.execute("SELECT * FROM candidates WHERE done=0").fetchall():
                _evaluate_candidate(conn, row, cache, today, stats)
    except Exception:
        logger.exception("Track-Record: Bewertung fehlgeschlagen")
    return stats


def _day(ts: str) -> date:
    return datetime.fromisoformat(str(ts)[:19]).date()


def _end_day(row) -> date | None:
    """Letzter Tag, der für diese Empfehlung zählt (Tag vor der Nachfolge-Empfehlung)."""
    return _day(row["superseded_at"]) if row["superseded_at"] else None


def _evaluate_trade(conn, row, cache, today, stats):
    created = _day(row["created_at"])
    end = _end_day(row)
    bars = [b for b in cache.bars(row["ticker"], created) if end is None or b["date"] < end.isoformat()]
    is_sell = row["action"] == "sell"
    entry, ref = row["entry_price"], row["ref_price"]

    if row["status"] == "pending":
        fill_price = fill_day = None
        is_limit = (row["action"] == "watch"
                    or (row["action"] == "buy" and entry and ref and entry < ref * (1 - LIMIT_TOLERANCE)))
        if not is_limit and bars:
            # Markt-Order (oder Limit nahe am Kurs): gilt am Anlegetag als ausgeführt.
            fill_price = entry if entry and ref and abs(entry / ref - 1) <= 0.02 else (ref or bars[0]["open"])
            fill_day = bars[0]["date"]
        elif is_limit:
            for b in bars:
                if b["low"] <= entry:
                    fill_price = min(b["open"], entry)
                    fill_day = b["date"]
                    break
        if fill_day is None:
            if end is not None or (today - created).days >= LIMIT_EXPIRE_DAYS:
                conn.execute("UPDATE recommendations SET status='expired', closed_at=? WHERE id=?",
                             ((end or today).isoformat(), row["id"]))
                stats["expired"] += 1
            return
        fd = date.fromisoformat(fill_day)
        fill_bench = cache.close_on(BENCHMARK_TICKER, fd) or row["bench_level"]
        fill_fx = cache.close_on("EURUSD=X", fd) or row["fx_eur_usd"]
        conn.execute("UPDATE recommendations SET status='open', filled_at=?, fill_price=?, fill_bench=?, "
                     "fill_fx=? WHERE id=?", (fill_day, fill_price, fill_bench, fill_fx, row["id"]))
        row = conn.execute("SELECT * FROM recommendations WHERE id=?", (row["id"],)).fetchone()
        stats["filled"] += 1

    fd = date.fromisoformat(row["filled_at"])
    stop, target = row["stop_loss"], row["target_price"]
    marks = json.loads(row["marks"] or "{}")
    exit_status = exit_price = exit_day = None
    walked = [b for b in bars if b["date"] > row["filled_at"]]
    for b in walked:
        # Tagesdaten verraten nicht, ob Stop/Ziel vor oder nach dem Fill lag —
        # daher erst ab dem Folgetag prüfen.
        hit_stop = stop is not None and ((b["high"] >= stop) if is_sell else (b["low"] <= stop))
        hit_target = target is not None and ((b["low"] <= target) if is_sell else (b["high"] >= target))
        if hit_stop:  # beides am selben Tag → konservativ: Stop zuerst
            exit_status = "stop_hit"
            exit_price = max(b["open"], stop) if is_sell else min(b["open"], stop)
        elif hit_target:
            exit_status = "target_hit"
            exit_price = min(b["open"], target) if is_sell else max(b["open"], target)
        if exit_status:
            exit_day = b["date"]
            break
        held = (date.fromisoformat(b["date"]) - fd).days
        for m in MTM_MARKS:
            if held >= m and str(m) not in marks:
                bd = date.fromisoformat(b["date"])
                ret, _, alpha = _returns(row, b["close"], cache.close_on("EURUSD=X", bd),
                                         cache.close_on(BENCHMARK_TICKER, bd))
                marks[str(m)] = {"date": b["date"], "return_pct": ret, "alpha_pct": alpha}
        if held >= HORIZON_DAYS:
            exit_status, exit_price, exit_day = "horizon", b["close"], b["date"]
            break

    if not exit_status and end is not None and today >= end:
        # Ersetzt: zum letzten Schluss vor der neuen Empfehlung schließen.
        last = walked[-1] if walked else (bars[-1] if bars else None)
        if last:
            exit_status, exit_price, exit_day = "superseded", last["close"], last["date"]
        else:
            conn.execute("UPDATE recommendations SET status='superseded', closed_at=? WHERE id=?",
                         (end.isoformat(), row["id"]))
            return

    if exit_status:
        ed = date.fromisoformat(exit_day)
        exit_bench = cache.close_on(BENCHMARK_TICKER, ed)
        exit_fx = cache.close_on("EURUSD=X", ed)
        ret, bret, alpha = _returns(row, exit_price, exit_fx, exit_bench)
        conn.execute(
            "UPDATE recommendations SET status=?, closed_at=?, exit_price=?, exit_bench=?, exit_fx=?, "
            "return_pct=?, bench_return_pct=?, alpha_pct=?, marks=? WHERE id=?",
            (exit_status, exit_day, exit_price, exit_bench, exit_fx, ret, bret, alpha,
             json.dumps(marks), row["id"]),
        )
        stats["closed"] += 1
    elif walked or bars:
        # Laufender Stand für die Bilanz (offene Positionen zum letzten Schluss).
        last = (walked or bars)[-1]
        ld = date.fromisoformat(last["date"])
        ret, _, alpha = _returns(row, last["close"], cache.close_on("EURUSD=X", ld),
                                 cache.close_on(BENCHMARK_TICKER, ld))
        marks["now"] = {"date": last["date"], "return_pct": ret, "alpha_pct": alpha}
        conn.execute("UPDATE recommendations SET marks=? WHERE id=?", (json.dumps(marks), row["id"]))


def _evaluate_stop(conn, row, cache, today, stats):
    """Stop-Pflege: Wurde der Stop ausgelöst, und was hat er gekostet?"""
    stop = row["stop_loss"]
    created = _day(row["created_at"])
    end = _end_day(row)
    marks = json.loads(row["marks"] or "{}")
    if row["status"] == "tracking":
        if stop is None:
            return
        triggered = False
        for b in cache.bars(row["ticker"], created):
            if b["date"] <= created.isoformat():
                continue
            if end is not None and b["date"] >= end.isoformat():
                break
            if b["low"] <= stop:
                conn.execute("UPDATE recommendations SET status='stop_triggered', closed_at=?, exit_price=? "
                             "WHERE id=?", (b["date"], min(b["open"], stop), row["id"]))
                stats["stops"] += 1
                row = conn.execute("SELECT * FROM recommendations WHERE id=?", (row["id"],)).fetchone()
                triggered = True
                break
        if not triggered:
            if (end is not None and today >= end) or (today - created).days >= HORIZON_DAYS:
                conn.execute("UPDATE recommendations SET status='done', closed_at=? WHERE id=?",
                             ((end or today).isoformat(), row["id"]))
            return

    # stop_triggered: Kursverlauf danach. Positiv = der Stop hat Rendite gekostet.
    sd = date.fromisoformat(row["closed_at"])
    exit_price = row["exit_price"]
    for b in cache.bars(row["ticker"], sd):
        held = (date.fromisoformat(b["date"]) - sd).days
        for m in POST_STOP_MARKS:
            if held >= m and str(m) not in marks and exit_price:
                marks[str(m)] = {"date": b["date"], "after_stop_pct": round((b["close"] / exit_price - 1) * 100, 2)}
    done = all(str(m) in marks for m in POST_STOP_MARKS)
    conn.execute("UPDATE recommendations SET marks=?, status=? WHERE id=?",
                 (json.dumps(marks), "done" if done else "stop_triggered", row["id"]))


def _evaluate_candidate(conn, row, cache, today, stats):
    created = _day(row["created_at"])
    marks = json.loads(row["marks"] or "{}")
    fake = {"action": "buy", "currency": row["currency"], "fill_price": row["ref_price"],
            "ref_price": row["ref_price"], "fx_eur_usd": row["fx_eur_usd"], "bench_level": row["bench_level"],
            "fill_fx": None, "fill_bench": None}
    bars = cache.bars(row["ticker"], created)
    for b in bars:
        held = (date.fromisoformat(b["date"]) - created).days
        for m in CANDIDATE_MARKS:
            if held >= m and str(m) not in marks:
                bd = date.fromisoformat(b["date"])
                ret, bret, alpha = _returns(fake, b["close"], cache.close_on("EURUSD=X", bd),
                                            cache.close_on(BENCHMARK_TICKER, bd))
                marks[str(m)] = {"date": b["date"], "return_pct": ret, "alpha_pct": alpha}
    if bars:
        ld = date.fromisoformat(bars[-1]["date"])
        ret, bret, alpha = _returns(fake, bars[-1]["close"], cache.close_on("EURUSD=X", ld),
                                    cache.close_on(BENCHMARK_TICKER, ld))
        marks["now"] = {"date": bars[-1]["date"], "return_pct": ret, "alpha_pct": alpha}
    done = all(str(m) in marks for m in CANDIDATE_MARKS)
    conn.execute("UPDATE candidates SET marks=?, done=? WHERE id=?", (json.dumps(marks), int(done), row["id"]))
    stats["candidates"] += 1


# ─── Tägliche Depot-NAV ──────────────────────────────────────

def record_nav(overview: dict, market_data: dict | None = None, day: date | None = None,
               bench_level: float | None = None) -> dict | None:
    """Speichert den Depotstand des Tages und verkettet die zeitgewichtete Rendite.

    Tagesrendite = Wert der GESTRIGEN Stückzahlen zu heutigen Kursen / Wert zu
    gestrigen Kursen − 1. Käufe, Verkäufe und Einzahlungen verfälschen sie damit nicht."""
    try:
        day = day or date.today()
        positions: dict[str, dict] = {}
        for p in overview.get("positions", []):
            t = p.get("ticker")
            if not t or not p.get("has_live_price"):
                continue
            agg = positions.setdefault(t, {"shares": 0.0, "price_eur": p.get("current_price_eur")})
            agg["shares"] += float(p.get("shares") or 0)
        if bench_level is None:
            bench_level = _bench(market_data)
        with _db() as conn:
            prev = conn.execute("SELECT * FROM nav_daily WHERE date<? ORDER BY date DESC LIMIT 1",
                                (day.isoformat(),)).fetchone()
            factor = 1.0
            if prev:
                prev_pos = json.loads(prev["positions"] or "{}")
                num = den = 0.0
                for t, pp in prev_pos.items():
                    now_p = (positions.get(t) or {}).get("price_eur")
                    if now_p and pp.get("price_eur"):
                        num += pp["shares"] * now_p
                        den += pp["shares"] * pp["price_eur"]
                r = (num / den - 1) if den > 0 else 0.0
                factor = (prev["twr_factor"] or 1.0) * (1 + r)
            conn.execute(
                "INSERT OR REPLACE INTO nav_daily (date, holdings_eur, cash_eur, total_eur, positions, "
                "twr_factor, bench_level, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                (day.isoformat(), overview.get("holdings_value_eur"), overview.get("cash_total"),
                 overview.get("total_value_eur"), json.dumps(positions), factor, bench_level,
                 _now().isoformat()),
            )
        return {"date": day.isoformat(), "twr_factor": factor}
    except Exception:
        logger.exception("Track-Record: NAV konnte nicht gespeichert werden")
        return None


def has_nav_for(day: date) -> bool:
    try:
        with _db() as conn:
            return conn.execute("SELECT 1 FROM nav_daily WHERE date=?", (day.isoformat(),)).fetchone() is not None
    except Exception:
        return False


def nav_performance(since: date | None = None) -> dict | None:
    """Depot-TWR und Benchmark seit `since` (Standard: erste Messung)."""
    try:
        with _db() as conn:
            q = "SELECT * FROM nav_daily" + (" WHERE date>=?" if since else "") + " ORDER BY date"
            rows = conn.execute(q, (since.isoformat(),) if since else ()).fetchall()
    except Exception:
        logger.exception("Track-Record: NAV-Auswertung fehlgeschlagen")
        return None
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    twr = (last["twr_factor"] / first["twr_factor"] - 1) * 100 if first["twr_factor"] else None
    bench = ((last["bench_level"] / first["bench_level"] - 1) * 100
             if first["bench_level"] and last["bench_level"] else None)
    cash_shares = [r["cash_eur"] / r["total_eur"] * 100 for r in rows if r["total_eur"]]
    return {
        "from": first["date"], "to": last["date"], "days": len(rows),
        "twr_pct": round(twr, 2) if twr is not None else None,
        "bench_pct": round(bench, 2) if bench is not None else None,
        "excess_pct": round(twr - bench, 2) if twr is not None and bench is not None else None,
        "avg_cash_pct": round(sum(cash_shares) / len(cash_shares), 1) if cash_shares else None,
        "total_eur_start": first["total_eur"], "total_eur_end": last["total_eur"],
    }


# ─── Auswertung ──────────────────────────────────────────────

def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95-%-Konfidenzintervall einer Trefferquote (Wilson), in Prozent."""
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def compute_summary() -> dict:
    """Kennzahlen für Prompt und UI."""
    try:
        with _db() as conn:
            recs = [dict(r) for r in conn.execute("SELECT * FROM recommendations").fetchall()]
            cands = [dict(r) for r in conn.execute("SELECT * FROM candidates").fetchall()]
    except Exception:
        logger.exception("Track-Record: Auswertung fehlgeschlagen")
        return {}

    trades = [r for r in recs if r["category"] == "trade"]
    closed = [r for r in trades if r["status"] in TRADE_CLOSED and r["return_pct"] is not None]
    open_ = [r for r in trades if r["status"] == "open"]
    buys_open = [json.loads(r["marks"] or "{}").get("now", {}) for r in open_ if r["action"] != "sell"]
    wins = sum(1 for r in closed if r["return_pct"] > 0)
    beat = [r for r in closed if r["alpha_pct"] is not None]
    beats = sum(1 for r in beat if r["alpha_pct"] > 0)

    holding = []
    for r in closed:
        try:
            holding.append((date.fromisoformat(r["closed_at"][:10]) - date.fromisoformat(r["filled_at"][:10])).days)
        except (TypeError, ValueError):
            pass

    stops = [r for r in recs if r["category"] == "stop"]
    triggered = [r for r in stops if r["status"] in ("stop_triggered", "done") and r["exit_price"]]
    after = {m: _mean(json.loads(r["marks"] or "{}").get(str(m), {}).get("after_stop_pct") for r in triggered)
             for m in POST_STOP_MARKS}

    cand_marks = [json.loads(c["marks"] or "{}") for c in cands]
    cand_90 = [m.get("90", {}).get("alpha_pct") for m in cand_marks]
    cand_now = [m.get("now", {}).get("alpha_pct") for m in cand_marks]
    acc_90 = [json.loads(r["marks"] or "{}").get("90", {}).get("alpha_pct")
              for r in trades if r["action"] != "sell" and r["filled_at"]]

    return {
        "closed_n": len(closed),
        "wins": wins,
        "hit_rate": round(wins / len(closed) * 100, 1) if closed else None,
        "hit_ci": wilson_interval(wins, len(closed)),
        "beat_n": len(beat),
        "beat_rate": round(beats / len(beat) * 100, 1) if beat else None,
        "beat_ci": wilson_interval(beats, len(beat)),
        "avg_return_pct": _mean(r["return_pct"] for r in closed),
        "avg_alpha_pct": _mean(r["alpha_pct"] for r in closed),
        "avg_holding_days": round(sum(holding) / len(holding)) if holding else None,
        "by_exit": {s: sum(1 for r in closed if r["status"] == s) for s in TRADE_CLOSED},
        "open_n": len(open_),
        "open_avg_alpha_pct": _mean(m.get("alpha_pct") for m in buys_open),
        "pending_n": sum(1 for r in trades if r["status"] == "pending"),
        "expired_n": sum(1 for r in trades if r["status"] == "expired"),
        "stops_n": len(stops),
        "stops_triggered_n": len(triggered),
        "after_stop_pct": after,
        "candidates_n": len(cands),
        "candidates_avg_alpha_90": _mean(cand_90),
        "candidates_n_90": sum(1 for x in cand_90 if x is not None),
        "candidates_avg_alpha_now": _mean(cand_now),
        "accepted_avg_alpha_90": _mean(acc_90),
        "accepted_n_90": sum(1 for x in acc_90 if x is not None),
        "nav": nav_performance(),
    }


def _pct(x, signed=True):
    if x is None:
        return "–"
    return f"{x:+.1f} %" if signed else f"{x:.1f} %"


def format_for_prompt(summary: dict | None = None) -> str:
    """Bilanz für den Briefing-Prompt — mit Stichprobengröße und Unsicherheit."""
    s = summary if summary is not None else compute_summary()
    if not s:
        return "Noch keine Bilanz verfügbar."
    lines = [f"EMPFEHLUNGS-BILANZ (Archiv, Bewertung über Tageshoch/-tief, Vergleich: {BENCHMARK_NAME})"]
    n = s.get("closed_n") or 0
    if n:
        ci = s.get("hit_ci")
        ci_str = f" (95-%-Intervall {ci[0]:.0f}–{ci[1]:.0f} %)" if ci else ""
        lines.append(f"  Abgeschlossene Ideen: {n} · im Plus: {s['wins']} = {s['hit_rate']:.0f} %{ci_str}")
        if s.get("beat_rate") is not None:
            bci = s.get("beat_ci")
            lines.append(f"  Besser als der Markt: {s['beat_rate']:.0f} % von {s['beat_n']}"
                         + (f" (95-%-Intervall {bci[0]:.0f}–{bci[1]:.0f} %)" if bci else ""))
        lines.append(f"  Ø Rendite {_pct(s.get('avg_return_pct'))} · Ø Überrendite {_pct(s.get('avg_alpha_pct'))}"
                     + (f" · Ø Haltedauer {s['avg_holding_days']} Tage" if s.get("avg_holding_days") is not None else ""))
        ex = s.get("by_exit") or {}
        lines.append(f"  Ausstiege: Ziel {ex.get('target_hit', 0)} · Stop {ex.get('stop_hit', 0)} · "
                     f"ersetzt {ex.get('superseded', 0)} · nach 1 Jahr bewertet {ex.get('horizon', 0)}")
        if n < MIN_SIGNAL_N:
            lines.append(f"  ⚠ Nur {n} Fälle — statistisch noch Rauschen. Ziehe daraus KEINE Lehre "
                         f"(weder mehr Vorsicht noch mehr Mut), erst ab {MIN_SIGNAL_N}.")
    else:
        lines.append("  Noch keine abgeschlossenen Ideen.")
    if s.get("open_n"):
        lines.append(f"  Laufende Ideen: {s['open_n']}, Ø Überrendite bisher {_pct(s.get('open_avg_alpha_pct'))}")
    if s.get("pending_n") or s.get("expired_n"):
        lines.append(f"  Limits: {s.get('pending_n', 0)} warten auf Ausführung, {s.get('expired_n', 0)} "
                     f"nie erreicht (zählen nicht als Treffer)")

    if s.get("stops_triggered_n"):
        a = s.get("after_stop_pct") or {}
        lines.append(f"  Stops ausgelöst: {s['stops_triggered_n']} · Kurs danach: "
                     f"30 Tage {_pct(a.get(30))}, 90 Tage {_pct(a.get(90))} "
                     f"(positiv = der Stop hat Rendite gekostet)")

    if s.get("candidates_n"):
        line = (f"  Schattenbuch abgelehnter Kandidaten: {s['candidates_n']} Titel · "
                f"Ø Überrendite bisher {_pct(s.get('candidates_avg_alpha_now'))}")
        if s.get("candidates_n_90"):
            line += f" · nach 90 Tagen {_pct(s.get('candidates_avg_alpha_90'))} (n={s['candidates_n_90']})"
        lines.append(line)
        if s.get("accepted_n_90"):
            lines.append(f"  Zum Vergleich deine Kaufideen nach 90 Tagen: {_pct(s.get('accepted_avg_alpha_90'))} "
                         f"(n={s['accepted_n_90']})")

    nav = s.get("nav")
    if nav and nav.get("twr_pct") is not None:
        lines.append(f"  Depot (zeitgewichtet, ohne Cash) {nav['from']} bis {nav['to']}: {_pct(nav['twr_pct'])} · "
                     f"{BENCHMARK_NAME} {_pct(nav.get('bench_pct'))} · Ø Cash-Quote {_pct(nav.get('avg_cash_pct'), False)}")
    return "\n".join(lines)


# ─── Input-Snapshots ─────────────────────────────────────────

SNAPSHOT_DIR = MEMORY_DIR / "briefing_inputs"
SNAPSHOT_KEEP = 200


def save_input_snapshot(system_prompt: str, prompt: str, response_text: str | None,
                        now: datetime | None = None) -> str | None:
    """Speichert Prompt + Antwort eines Briefings (gzip), damit spätere Prompt-Varianten
    auf identischen Daten verglichen werden können."""
    import gzip
    try:
        now = now or _now()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / f"{now.strftime('%Y-%m-%d_%H%M%S')}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"created_at": now.isoformat(), "system": system_prompt, "prompt": prompt,
                       "response": response_text}, f, ensure_ascii=False)
        old = sorted(SNAPSHOT_DIR.glob("*.json.gz"))
        for p in old[:-SNAPSHOT_KEEP]:
            p.unlink(missing_ok=True)
        return str(path)
    except Exception:
        logger.exception("Track-Record: Input-Snapshot fehlgeschlagen")
        return None


# ─── Täglicher Lauf ──────────────────────────────────────────

def run_daily(portfolio: dict | None = None) -> dict:
    """Tagesabschluss: Kurse holen, NAV speichern, laufende Empfehlungen bewerten.

    Nutzt nur yfinance (keine kostenpflichtigen APIs)."""
    from src.data.market import collect_all_market_data, load_portfolio
    from src.web.services.portfolio_service import compute_portfolio_overview
    portfolio = portfolio or load_portfolio()
    market_data = collect_all_market_data(portfolio)
    overview = compute_portfolio_overview(portfolio, market_data)
    nav = record_nav(overview, market_data)
    stats = evaluate_open()
    logger.info("Track-Record Tageslauf: NAV %s, Bewertung %s", nav, stats)
    return {"nav": nav, "evaluation": stats, "market_data": market_data}
