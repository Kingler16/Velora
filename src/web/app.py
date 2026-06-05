"""
FastAPI Web-Dashboard für Velora.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import hmac

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.i18n import get_translations
from src.web.services.portfolio_service import (
    load_portfolio,
    load_watchlist,
    compute_portfolio_overview,
    compute_index_data,
)
from src.web.services.cache_service import (
    get_market_data,
    get_macro_data,
    get_news_data,
    get_calendar_data,
    get_cache_status,
    get_monthly_snapshots,
    get_briefings,
    get_recommendations,
    get_notes,
)
from src.analysis.performance import compute_benchmark_data, compute_tax_loss_data, compute_recommendation_data
from src.data.cache import save_cache
from src.data.fx import get_eur_usd, safe_eur_usd

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Background refresh state
_refresh_running = False
_refresh_lock = asyncio.Lock()


def format_eur(value):
    """Jinja2 Filter: Zahl als EUR formatieren."""
    if value is None:
        return "–"
    return f"{value:,.2f}€".replace(",", "X").replace(".", ",").replace("X", ".")


_EUR_SUFFIXES = (".DE", ".AS", ".PA", ".VI", ".MI", ".MC", ".BR", ".LS", ".HE", ".ST", ".OL", ".F", ".DU")
_EUR_ISIN_PREFIXES = ("AT0", "DE0", "FR0", "NL0", "IE0", "ES0", "IT0", "BE0", "FI0", "PT0", "LU0")


def _ticker_currency(ticker: str) -> str:
    """Leitet die Quote-Währung aus dem Ticker-Suffix / ISIN-Präfix ab (CODE-Rückgabe).

    Achtung: gepunktete US-Share-Classes (BRK.B, BF.B) sind USD — daher kein
    pauschales "." → EUR mehr. Wo eine echte currency aus market_data vorliegt,
    hat diese Vorrang (siehe Filter unten / recommendations_page).
    """
    if not ticker:
        return "USD"
    tk = ticker.upper()
    if tk.endswith(_EUR_SUFFIXES) or tk.startswith(_EUR_ISIN_PREFIXES):
        return "EUR"
    if tk.endswith(".L"):
        return "GBP"
    if tk.endswith((".SW", ".VX")):
        return "CHF"
    if tk.endswith((".TO", ".V")):
        return "CAD"
    return "USD"


def _de_num(value: float) -> str:
    """Zahl im deutschen Format: 1.234,56."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _symbolize(value, currency: str) -> str:
    """Formatiert value mit dem korrekten Währungs-Symbol (deutsches Zahlenformat)."""
    num = _de_num(value)
    if currency in ("GBP", "GBp"):
        return f"£{num}"
    if currency == "CHF":
        return f"{num} CHF"
    if currency == "CAD":
        return f"C${num}"
    if currency == "EUR":
        return f"{num}€"
    return f"${num}"  # USD (Default)


def format_price(value, ticker=None, currency=None):
    """Jinja2 Filter: Preis in der korrekten Quote-Währung.

    Wenn `currency` (echter Code aus market_data) übergeben ist, hat sie Vorrang;
    sonst Fallback auf die Heuristik _ticker_currency(ticker). Backward-kompatibel.
    Verwendung: {{ rec.entry_price|price(rec.ticker, rec._ccy) }}
    Vermeidet den kritischen Fehler, USD-Preise (META=$610) als EUR (610€) zu rendern.
    """
    if value is None:
        return "–"
    curr = currency or _ticker_currency(ticker)
    return _symbolize(value, curr)


def format_price_alt(value, ticker=None, eur_usd: float = None, currency=None):
    """Jinja2 Filter: ≈-Sekundärumrechnung — NUR für EUR/USD (dafür haben wir den Kurs).

    Für USD-Ticker → EUR-Wert (value / eur_usd). Für EUR-Ticker → USD-Wert (value * eur_usd).
    Für GBP/CHF/CAD "" (kein Kurs vorhanden). Verwendung: {{ x|price_alt(ticker, eur_usd, rec._ccy) }}
    Gibt "" zurück wenn eur_usd fehlt — Template überspringt dann den Sekundär-Block.
    """
    if value is None or not eur_usd:
        return ""
    curr = currency or _ticker_currency(ticker)
    if curr == "EUR":
        return f"${_de_num(value * eur_usd)}"
    if curr == "USD":
        return f"{_de_num(value / eur_usd)}€"
    return ""  # GBP/CHF/CAD: kein Umrechnungskurs vorhanden


def format_pct(value):
    """Jinja2 Filter: Zahl als Prozent formatieren."""
    if value is None or not isinstance(value, (int, float)):
        return "–"
    return f"{value:+.1f}%"


def format_number(value, decimals=2):
    """Jinja2 Filter: Zahl formatieren."""
    if value is None:
        return "–"
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Velora Dashboard gestartet")
    from src.data.cache import get_cache_age_minutes
    from src.chat.db import init_db as init_chat_db
    init_chat_db()
    logger.info("Chat-DB initialisiert")
    age = get_cache_age_minutes("market_data")
    if age is None:
        logger.info("Kein Cache vorhanden — starte automatischen Daten-Refresh...")
        asyncio.create_task(_run_refresh())
    else:
        logger.info(f"Cache gefunden (Alter: {age:.0f} Minuten)")
    yield
    logger.info("Velora Dashboard gestoppt")


app = FastAPI(title="Velora Dashboard", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Jinja2 custom filters
templates.env.filters["eur"] = format_eur
templates.env.filters["pct"] = format_pct
templates.env.filters["number"] = format_number
templates.env.filters["price"] = format_price
templates.env.filters["price_alt"] = format_price_alt

# Chat-Router
from src.chat.routes import router as chat_router
app.include_router(chat_router)


@app.get("/install", response_class=HTMLResponse)
async def install_page(request: Request):
    return templates.TemplateResponse(request, "install.html", _ctx(request, "install"))

# PWA-Router (Manifest + Service Worker auf Root-Scope)
from src.web.routes.pwa import router as pwa_router
app.include_router(pwa_router)

# Push-Notification-Router
from src.web.routes.push import router as push_router
app.include_router(push_router)

# Share-Target-Router (Screenshot via iOS-Share-Sheet)
from src.web.routes.share import router as share_router
app.include_router(share_router)


from src.config_loader import load_settings as _load_settings_impl


def _load_settings() -> dict:
    """Liest settings.json mit ENV-Overrides (siehe src/config_loader.py)."""
    return _load_settings_impl()


def _get_lang() -> str:
    """Liest die Sprache aus settings.json."""
    return _load_settings().get("user", {}).get("language", "de")


def _compute_asset_version() -> str:
    """Einmal beim Start berechneter Cache-Bust-Key fuer Static-Assets.
    Nutzt current Git-SHA wenn verfuegbar, sonst Process-Start-Zeit."""
    import subprocess as _sp
    import time as _time
    try:
        repo = Path(__file__).parent.parent.parent
        res = _sp.run(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return str(int(_time.time()))


_ASSET_VERSION = _compute_asset_version()


def _ctx(request, page: str, **extra) -> dict:
    """Baut den Template-Kontext mit Übersetzungen."""
    lang = _get_lang()
    t = get_translations(lang)
    return {"request": request, "page": page, "t": t, "lang": lang, "asset_v": _ASSET_VERSION, **extra}


# ─── HTML Pages ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    portfolio = load_portfolio()
    market_data = get_market_data()
    overview = compute_portfolio_overview(portfolio, market_data)
    indices = compute_index_data(market_data)
    snapshots = get_monthly_snapshots()
    cache_status = get_cache_status()

    return templates.TemplateResponse(request, "dashboard.html", _ctx(request, "dashboard",
        overview=overview, indices=indices, snapshots=snapshots, cache_status=cache_status,
    ))


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(request: Request):
    portfolio = load_portfolio()
    market_data = get_market_data()
    overview = compute_portfolio_overview(portfolio, market_data)
    cache_status = get_cache_status()
    settings = _load_settings()
    default_currency = settings.get("user", {}).get("default_currency", "EUR")

    return templates.TemplateResponse(request, "portfolio.html", _ctx(request, "portfolio",
        overview=overview, portfolio_raw=portfolio, cache_status=cache_status,
        default_currency=default_currency,
    ))


@app.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request):
    portfolio = load_portfolio()
    market_data = get_market_data()
    overview = compute_portfolio_overview(portfolio, market_data)
    snapshots = get_monthly_snapshots()
    cache_status = get_cache_status()
    benchmarks = compute_benchmark_data(market_data)
    tax_loss = compute_tax_loss_data(portfolio, market_data) if market_data.get("positions") else None
    settings = _load_settings()
    kest_mode = settings.get("user", {}).get("kest_mode", "per_account")

    return templates.TemplateResponse(request, "analysis.html", _ctx(request, "analysis",
        overview=overview, snapshots=snapshots, cache_status=cache_status, benchmarks=benchmarks,
        tax_loss=tax_loss, kest_mode=kest_mode,
    ))


@app.get("/market", response_class=HTMLResponse)
async def market_page(request: Request):
    market_data = get_market_data()
    macro_data = get_macro_data()
    news_data = get_news_data()
    calendar_data = get_calendar_data()
    indices = compute_index_data(market_data)
    cache_status = get_cache_status()

    # Sector Heatmap: Durchschnittliche Tagesveränderung pro Sektor
    sector_heatmap = {}
    for ticker, pos in market_data.get("positions", {}).items():
        price = pos.get("price", {})
        sector = price.get("sector")
        change = price.get("change_pct")
        if sector and change is not None:
            sector_heatmap.setdefault(sector, []).append(change)
    sector_heatmap = {s: round(sum(c) / len(c), 2) for s, c in sector_heatmap.items()}

    return templates.TemplateResponse(request, "market.html", _ctx(request, "market",
        indices=indices, macro=macro_data, calendar=calendar_data, cache_status=cache_status,
        news=news_data or {}, sector_heatmap=sector_heatmap,
    ))


@app.get("/briefings", response_class=HTMLResponse)
async def briefings_page(request: Request):
    return templates.TemplateResponse(request, "briefings.html", _ctx(request, "briefings",
        briefings=get_briefings(), notes=get_notes(),
    ))


def _resolve_ticker_currency(ticker: str, md: dict) -> str:
    """Echte Quote-Währung eines Tickers aus market_data (positions/watchlist) auflösen,
    sonst Fallback auf die Suffix-Heuristik. Gibt einen Währungs-CODE zurück."""
    if ticker and md:
        for bucket in ("positions", "watchlist"):
            entry = (md.get(bucket) or {}).get(ticker)
            if entry:
                ccy = (entry.get("price") or {}).get("currency")
                if ccy:
                    return ccy
    return _ticker_currency(ticker)


@app.get("/recommendations", response_class=HTMLResponse)
async def recommendations_page(request: Request):
    md = get_market_data()
    eur_usd = safe_eur_usd(md)
    recommendations = get_recommendations()
    # Anzeige-Währung pro Empfehlung serverseitig auflösen (echte currency hat Vorrang).
    for rec in recommendations:
        if isinstance(rec, dict):
            rec["_ccy"] = _resolve_ticker_currency(rec.get("ticker", ""), md)
    return templates.TemplateResponse(request, "recommendations.html", _ctx(request, "recommendations",
        recommendations=recommendations, notes=get_notes(), eur_usd=eur_usd,
    ))


# ─── Secrets-Maskierung & Auth-Gate ──────────────────────────
# Secrets dürfen nie im Klartext ins ausgelieferte HTML. Auth-Gate ist OFF
# solange kein web.auth_token in settings.json steht (kein Lockout beim Deploy);
# sobald gesetzt, verlangt jede nicht-öffentliche Route ein Cookie.

_SECRET_PATHS = (("telegram", "bot_token"), ("brave_search", "api_key"),
                 ("fred", "api_key"), ("finnhub", "api_key"))


def _mask_secret(value: str) -> str:
    """4 Anfang + 4 Ende, Rest verdeckt. Kurze Werte (<8) unverändert (kein Key)."""
    if not value or len(value) < 8:
        return value
    return value[:4] + "..." + value[-4:]


def _mask_settings(settings: dict) -> dict:
    """Kopie mit maskierten Secret-Feldern — für die server-gerenderte Settings-Seite."""
    import copy
    masked = copy.deepcopy(settings)
    for sec, key in _SECRET_PATHS:
        node = masked.get(sec)
        if isinstance(node, dict) and node.get(key):
            node[key] = _mask_secret(node[key])
    return masked


def _keep_or_update(stored: str, incoming) -> str:
    """Beim Speichern: maskierten Platzhalter oder Leerwert NICHT übernehmen —
    sonst überschreibt die maskierte Anzeige das echte Secret."""
    incoming = (incoming or "").strip()
    if not incoming or incoming == _mask_secret(stored or ""):
        return stored or ""
    return incoming


def _auth_token() -> str:
    return ((_load_settings().get("web", {}) or {}).get("auth_token") or "").strip()


_AUTH_PUBLIC = ("/static", "/login", "/sw.js", "/manifest", "/offline",
                "/favicon", "/apple-touch-icon", "/icons")


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    token = _auth_token()
    if token:
        path = request.url.path
        if not any(path == p or path.startswith(p) for p in _AUTH_PUBLIC):
            cookie = request.cookies.get("velora_auth", "")
            if not (cookie and hmac.compare_digest(cookie, token)):
                if path.startswith("/api"):
                    return JSONResponse({"error": "Authentifizierung erforderlich"}, status_code=401)
                return RedirectResponse("/login", status_code=302)
    return await call_next(request)


_LOGIN_HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Velora · Login</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0d0f12;color:#e8eaed;font-family:Inter,system-ui,sans-serif}
.card{background:#161a1f;border:1px solid #232830;border-radius:16px;padding:32px;width:min(360px,90vw)}
h1{font-size:18px;margin:0 0 4px}p.sub{color:#8b929c;font-size:13px;margin:0 0 20px}
input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid #2a2f37;background:#0d0f12;
color:#e8eaed;font-size:15px;margin-bottom:12px;font-family:inherit}
button{width:100%;padding:12px;border:0;border-radius:10px;background:#3b82f6;color:#fff;font-size:15px;
font-weight:600;cursor:pointer;font-family:inherit}button:active{opacity:.85}
.err{color:#e5484d;font-size:13px;margin:8px 0 0;min-height:18px}
</style></head><body><div class="card">
<h1>Velora</h1><p class="sub">Zugang geschützt — bitte Passwort eingeben.</p>
<input id="tok" type="password" placeholder="Passwort" autofocus autocomplete="current-password">
<button onclick="go()">Anmelden</button><p class="err" id="err"></p>
<script>
const go=async()=>{const t=document.getElementById('tok').value;
const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t})});
if(r.ok){location.href='/'}else{document.getElementById('err').textContent='Falsches Passwort'}};
document.getElementById('tok').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
</script></div></body></html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not _auth_token():
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(_LOGIN_HTML)


@app.post("/login")
async def login_submit(request: Request):
    token = _auth_token()
    try:
        body = await request.json()
    except Exception:
        body = {}
    supplied = (body.get("token") or "").strip()
    if token and hmac.compare_digest(supplied, token):
        resp = JSONResponse({"status": "ok"})
        resp.set_cookie("velora_auth", token, max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="lax")
        return resp
    return JSONResponse({"error": "Falsches Passwort"}, status_code=401)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    import json as _json
    settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
    with open(settings_path) as f:
        settings = _json.load(f)
    portfolio = load_portfolio()

    # Secrets NICHT im Klartext ins HTML — nur maskiert anzeigen.
    settings = _mask_settings(settings)

    return templates.TemplateResponse(request, "settings.html", _ctx(request, "settings",
        settings=settings, accounts=list(portfolio.get("accounts", {}).keys()), portfolio=portfolio,
    ))


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", _ctx(request, "chat"))


# ─── HTMX Partials ───────────────────────────────────────────

@app.get("/api/partial/indices", response_class=HTMLResponse)
async def partial_indices():
    """HTMX partial: Index-Leiste HTML."""
    market_data = get_market_data()
    indices = compute_index_data(market_data)
    if not indices:
        return '<div class="index-bar" style="color:var(--text-muted);font-size:13px;">Keine Index-Daten</div>'

    html = '<div class="index-bar">'
    for idx in indices:
        val = idx.get("value")
        change = idx.get("change_pct")
        val_str = f"{val:,.4f}" if idx["name"] == "EUR/USD" and val else (f"{val:,.0f}" if val else "–")
        change_cls = "positive" if change and change >= 0 else "negative" if change else ""
        change_str = f"{change:+.1f}%" if change is not None else ""
        html += f'''<div class="index-item">
            <span class="index-name">{idx["name"]}</span>
            <span class="index-value">{val_str}</span>
            <span class="index-change {change_cls}">{change_str}</span>
        </div>'''
    html += '</div>'
    return html


@app.get("/api/partial/cache-status", response_class=HTMLResponse)
async def partial_cache_status():
    """HTMX partial: Cache-Status als HTML für die Sidebar."""
    status = get_cache_status()
    market = status.get("market_data", {})

    if _refresh_running:
        return '<span class="cache-dot stale"></span> Daten werden geladen...'

    if market.get("available"):
        age = market.get("age_minutes", 0)
        ts = market.get("timestamp", "")
        if age < 60:
            dot = "fresh"
            label = f"Aktuell ({ts})"
        elif age < 360:
            dot = "stale"
            label = f"{int(age)}min alt ({ts})"
        else:
            dot = "stale"
            label = f"{int(age / 60)}h alt ({ts})"
        return f'<span class="cache-dot {dot}"></span> {label}'
    else:
        return '<span class="cache-dot missing"></span> Keine Daten — klicke Aktualisieren'


# ─── JSON API ────────────────────────────────────────────────

@app.get("/api/portfolio/summary")
async def api_portfolio_summary():
    portfolio = load_portfolio()
    market_data = get_market_data()
    overview = compute_portfolio_overview(portfolio, market_data)
    return JSONResponse(overview)


@app.get("/api/portfolio/history")
async def api_portfolio_history():
    return JSONResponse(get_monthly_snapshots())


@app.get("/api/market/indices")
async def api_market_indices():
    market_data = get_market_data()
    return JSONResponse(compute_index_data(market_data))


@app.get("/api/market/macro")
async def api_market_macro():
    return JSONResponse(get_macro_data())


@app.get("/api/briefings")
async def api_briefings():
    return JSONResponse(get_briefings())


@app.get("/api/recommendations")
async def api_recommendations():
    return JSONResponse(get_recommendations())


@app.get("/api/calendar")
async def api_calendar():
    return JSONResponse(get_calendar_data())


@app.get("/api/cache/status")
async def api_cache_status():
    return JSONResponse(get_cache_status())


# ─── Trade Logging ───────────────────────────────────────────

@app.post("/api/trade")
async def api_log_trade(request: Request):
    """Loggt einen Kauf oder Verkauf."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Ungültiger JSON-Body"}, status_code=400)

    action = body.get("action")
    ticker = body.get("ticker", "").strip().upper()
    account = body.get("account", "")
    trade_currency = body.get("trade_currency", "EUR")

    try:
        shares = float(body.get("shares", 0))
        price = float(body.get("price", 0))
    except (ValueError, TypeError):
        return JSONResponse({"error": "shares und price müssen Zahlen sein"}, status_code=400)

    if action not in ("buy", "sell"):
        return JSONResponse({"error": "action muss 'buy' oder 'sell' sein"}, status_code=400)
    if not ticker:
        return JSONResponse({"error": "Ticker fehlt"}, status_code=400)
    if shares <= 0 or price <= 0:
        return JSONResponse({"error": "shares und price müssen > 0 sein"}, status_code=400)

    # USD → EUR umrechnen für buy_in_eur und Cash-Tracking.
    # Trade-Pfad: bei fehlendem/unplausiblem EUR/USD-Kurs den USD-Trade ABLEHNEN,
    # statt einen falschen, steuerrelevanten Buy-In 1:1 als EUR zu verbuchen.
    price_eur = price
    md = get_market_data()
    if trade_currency == "USD":
        eur_usd = get_eur_usd(md)
        if eur_usd is None:
            return JSONResponse(
                {"error": "EUR/USD-Kurs nicht verfügbar — USD-Trade abgelehnt, bitte Daten aktualisieren"},
                status_code=400,
            )
        price_eur = price / eur_usd

    from src.delivery.telegram import update_portfolio_position, close_recommendation_on_trade

    portfolio = load_portfolio()
    if account not in portfolio.get("accounts", {}):
        return JSONResponse({"error": f"Account '{account}' nicht gefunden"}, status_code=404)

    from src.delivery.push_sender import send_push_safe

    success = update_portfolio_position(action, ticker, shares, price_eur)
    if success:
        close_recommendation_on_trade(ticker, action)
        currency_sym = '€' if trade_currency == 'EUR' else '$'
        action_label = 'Kauf' if action == 'buy' else 'Verkauf'
        send_push_safe(
            category="trade_confirmed",
            title=f"{action_label}: {ticker}",
            body=f"{shares} × @ {price}{currency_sym} auf {account}",
            url="/portfolio",
            tag=f"trade-{ticker}",
            data={"ticker": ticker, "action": action, "shares": shares, "price": price},
        )
        return JSONResponse({"status": "ok", "message": f"{shares}x {ticker} {'gekauft' if action == 'buy' else 'verkauft'} @ {price}{currency_sym}"})
    else:
        # Position nicht gefunden — bei Kauf neue Position anlegen (mit Lock + Cash-Update)
        if action == "buy":
            from src.delivery.portfolio_io import add_new_position
            from src.data.market import fetch_price_data
            # Ticker gegen yfinance validieren — None = ungültiger Ticker (Tippfehler).
            price_data = fetch_price_data(ticker)
            if price_data is None:
                return JSONResponse(
                    {"error": f"Ticker '{ticker}' nicht gefunden — Tippfehler? Keine Position angelegt"},
                    status_code=404,
                )
            # Echte Quote-Währung aus dem Lookup übernehmen statt aus dem Ticker zu raten.
            pos_currency = price_data.get("currency") or _ticker_currency(ticker)
            created = add_new_position(ticker, shares, price_eur, account, trade_currency=pos_currency)
            if created:
                close_recommendation_on_trade(ticker, action)
                try:
                    from src.web.services.portfolio_service import update_region_on_trade
                    update_region_on_trade("buy", ticker)
                except Exception:
                    pass
                send_push_safe(
                    category="trade_confirmed",
                    title=f"Neue Position: {ticker}",
                    body=f"{shares} × @ {price} in {account}",
                    url="/portfolio",
                    tag=f"trade-{ticker}",
                    data={"ticker": ticker, "action": action, "shares": shares, "price": price, "new_position": True},
                )
                return JSONResponse({"status": "ok", "message": f"Neue Position: {shares}x {ticker} @ {price} in {account}"})

        return JSONResponse({"error": f"Ticker {ticker} nicht gefunden in {account}"}, status_code=404)


@app.get("/api/accounts")
async def api_accounts():
    """Gibt verfügbare Accounts zurück."""
    portfolio = load_portfolio()
    accounts = list(portfolio.get("accounts", {}).keys())
    return JSONResponse(accounts)


# ─── Recommendation Management ───────────────────────────────

@app.post("/api/recommendations/close")
async def api_close_recommendation(request: Request):
    """Schließt eine Empfehlung als ausgeführt."""
    import json as _json
    body = await request.json()
    ticker = body.get("ticker", "").strip()
    status = body.get("status", "executed")  # executed, target_hit, stop_hit, cancelled

    if not ticker:
        return JSONResponse({"error": "Ticker fehlt"}, status_code=400)

    recs_path = Path(__file__).parent.parent.parent / "memory" / "recommendations.json"
    if not recs_path.exists():
        return JSONResponse({"error": "Keine Empfehlungen"}, status_code=404)

    with open(recs_path) as f:
        recs = _json.load(f)

    found = False
    for r in recs:
        if r.get("status") == "open" and (r.get("ticker") == ticker or r.get("ticker", "").split(".")[0] == ticker):
            r["status"] = status
            r["outcome"] = body.get("outcome")
            found = True

    if found:
        with open(recs_path, "w") as f:
            _json.dump(recs, f, indent=2, ensure_ascii=False)
        return JSONResponse({"status": "ok", "message": f"{ticker} als {status} markiert"})
    else:
        return JSONResponse({"error": f"Keine offene Empfehlung für {ticker}"}, status_code=404)


# ─── Settings API ────────────────────────────────────────────

@app.post("/api/settings")
async def api_save_settings(request: Request):
    """Speichert geänderte Einstellungen."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Ungültiger JSON-Body"}, status_code=400)

    settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
    with open(settings_path) as f:
        settings = _json.load(f)

    # Nur erlaubte Felder updaten. Secrets: maskierten Platzhalter / Leerwert
    # NICHT übernehmen (sonst überschreibt die maskierte Anzeige das echte Secret).
    if "telegram" in body:
        tg = body["telegram"]
        if "bot_token" in tg:
            cur = settings.setdefault("telegram", {}).get("bot_token", "")
            settings["telegram"]["bot_token"] = _keep_or_update(cur, tg["bot_token"])
        if "chat_id" in tg:
            settings.setdefault("telegram", {})["chat_id"] = tg["chat_id"]
    if "brave_search" in body:
        cur = settings.setdefault("brave_search", {}).get("api_key", "")
        settings["brave_search"]["api_key"] = _keep_or_update(cur, body["brave_search"].get("api_key", ""))
    if "fred" in body:
        cur = settings.setdefault("fred", {}).get("api_key", "")
        settings["fred"]["api_key"] = _keep_or_update(cur, body["fred"].get("api_key", ""))
    if "finnhub" in body:
        cur = settings.setdefault("finnhub", {}).get("api_key", "")
        settings["finnhub"]["api_key"] = _keep_or_update(cur, body["finnhub"].get("api_key", ""))
    if "user" in body:
        user = body["user"]
        settings.setdefault("user", {})
        if "language" in user:
            settings["user"]["language"] = user["language"]
        if "kest_mode" in user:
            settings["user"]["kest_mode"] = user["kest_mode"]
        if "default_currency" in user:
            settings["user"]["default_currency"] = user["default_currency"]
    if "schedule" in body:
        sched = body["schedule"]
        settings.setdefault("schedule", {})
        if "briefing_days" in sched:
            settings["schedule"]["briefing_days"] = sched["briefing_days"]
        if "briefing_time" in sched:
            settings["schedule"]["briefing_time"] = sched["briefing_time"]
    if "web" in body:
        web = body["web"]
        settings.setdefault("web", {})
        if "port" in web:
            settings["web"]["port"] = int(web["port"])

    with open(settings_path, "w") as f:
        _json.dump(settings, f, indent=2, ensure_ascii=False)

    return JSONResponse({"status": "ok", "message": "Einstellungen gespeichert"})


@app.get("/api/settings")
async def api_get_settings():
    """Gibt aktuelle Einstellungen zurück (API Keys maskiert)."""
    import json as _json
    settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
    with open(settings_path) as f:
        settings = _json.load(f)

    # API Keys maskieren für die Anzeige (geteilter Helfer mit der Settings-Seite)
    safe = {
        "telegram": {
            "bot_token": _mask_secret(settings.get("telegram", {}).get("bot_token", "")),
            "chat_id": settings.get("telegram", {}).get("chat_id", ""),
        },
        "brave_search": {"api_key": _mask_secret(settings.get("brave_search", {}).get("api_key", ""))},
        "fred": {"api_key": _mask_secret(settings.get("fred", {}).get("api_key", ""))},
        "finnhub": {"api_key": _mask_secret(settings.get("finnhub", {}).get("api_key", ""))},
        "schedule": settings.get("schedule", {}),
        "user": settings.get("user", {}),
        "web": settings.get("web", {}),
    }
    return JSONResponse(safe)


# ─── System Update ───────────────────────────────────────────

@app.get("/api/system/version")
async def api_system_version():
    """Gibt aktuelle Git-Version + Commit-Subject zurück."""
    import subprocess as _sp
    import shutil as _shutil
    repo_dir = Path(__file__).parent.parent.parent
    # Explizites PATH + safe.directory damit's im systemd-Service-Kontext (minimal
    # env, running als root auf admin-owned repo) funktioniert.
    env = {
        "PATH": os.environ.get("PATH", "") + ":/usr/bin:/usr/local/bin",
        "HOME": os.environ.get("HOME", "/root"),
    }
    git_bin = _shutil.which("git", path=env["PATH"]) or "git"
    base = [git_bin, "-c", f"safe.directory={repo_dir}", "-C", str(repo_dir)]
    try:
        head = _sp.run(base + ["rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=5, env=env)
        if head.returncode != 0:
            return JSONResponse({
                "available": False,
                "reason": "git_error",
                "detail": (head.stderr or head.stdout or "").strip()[:200],
            })
        sha = head.stdout.strip()
        subject = _sp.run(base + ["log", "-1", "--format=%s"],
                          capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        date = _sp.run(base + ["log", "-1", "--format=%cI"],
                       capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        return JSONResponse({
            "available": True,
            "sha": sha,
            "short_sha": sha[:7],
            "subject": subject,
            "date": date,
        })
    except FileNotFoundError:
        return JSONResponse({"available": False, "reason": "git_not_installed"})
    except Exception as e:
        return JSONResponse({"available": False, "reason": str(e)[:200]})


@app.post("/api/system/update")
async def api_system_update():
    """Fuehrt git pull aus und startet velora-web + velora-bot neu.
    Portfolio-/Config-Daten in .gitignore werden nicht angefasst.
    Restart wird detached gestartet, damit die HTTP-Response durchkommt."""
    import subprocess as _sp
    repo_dir = Path(__file__).parent.parent.parent
    script = repo_dir / "scripts" / "system_update.sh"

    if not script.exists():
        return JSONResponse({"status": "error", "error": "update_script_missing"}, status_code=500)

    try:
        result = _sp.run(["bash", str(script)], capture_output=True, text=True, timeout=60,
                         env={
                             "VELORA_REPO_DIR": str(repo_dir),
                             "PATH": os.environ.get("PATH", ""),
                             # HOME muss durchgereicht werden, damit git seine global-config
                             # (insb. safe.directory) aus ~/.gitconfig lesen kann. Ohne HOME
                             # wirft git bei root+admin-Repo "dubious ownership".
                             "HOME": os.environ.get("HOME", "/root"),
                         })
    except _sp.TimeoutExpired:
        return JSONResponse({"status": "error", "error": "update_timeout"}, status_code=504)
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)[:200]}, status_code=500)

    stdout_last = (result.stdout or "").strip().splitlines()[-1] if result.stdout else ""
    stderr_tail = (result.stderr or "").strip()[-400:]

    import json as _json
    parsed = None
    try:
        parsed = _json.loads(stdout_last)
    except Exception:
        pass

    if result.returncode != 0 or not parsed or parsed.get("error"):
        return JSONResponse({
            "status": "error",
            "error": (parsed or {}).get("error", "update_failed"),
            "detail": (parsed or {}).get("detail") or stderr_tail,
        }, status_code=500)

    # Restart detached — response muss zuerst raus.
    # sleep 2 gibt dem Browser Zeit, die Response zu empfangen.
    try:
        _sp.Popen(
            ["bash", "-c", "sleep 2 && systemctl restart velora-web velora-bot"],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
        parsed["restart_scheduled"] = True
    except Exception as e:
        parsed["restart_scheduled"] = False
        parsed["restart_error"] = str(e)[:200]

    return JSONResponse(parsed)


def _maybe_append_monthly_snapshot(overview: dict) -> bool:
    """Haengt einen Snapshot fuer den aktuellen Monat an monthly_snapshots.json an,
    falls fuer diesen Monat noch keiner existiert. Returns True wenn geschrieben."""
    from datetime import datetime
    import json
    memory_dir = Path(__file__).parent.parent.parent / "memory"
    path = memory_dir / "monthly_snapshots.json"
    memory_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    if path.exists():
        try:
            with open(path) as f:
                snapshots = json.load(f)
        except Exception:
            snapshots = []
    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    if any(s.get("month") == month_key for s in snapshots):
        return False
    snap = {
        "date": now.isoformat(),
        "month": month_key,
        "total_value": round(overview.get("total_value_eur", 0), 2),
        "portfolio_value": round(overview.get("total_value_eur", 0), 2),
        "holdings_value_eur": round(overview.get("holdings_value_eur", 0), 2),
        "cash_total": round(overview.get("cash_total", 0), 2),
        "total_pnl_eur": round(overview.get("total_pnl_eur", 0), 2),
        "total_pnl_pct": round(overview.get("total_pnl_pct", 0), 2),
        "position_count": len(overview.get("positions", [])),
    }
    snapshots.append(snap)
    snapshots = snapshots[-24:]
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(snapshots, f, indent=2, default=str)
    tmp.replace(path)
    logger.info(f"Monthly-Snapshot fuer {month_key} angelegt: {snap['total_value']}€")
    return True


@app.post("/api/refresh")
async def api_refresh(background_tasks: BackgroundTasks):
    global _refresh_running
    async with _refresh_lock:
        if _refresh_running:
            return JSONResponse({"status": "already_running"})
        _refresh_running = True
    background_tasks.add_task(_run_refresh)
    return JSONResponse({"status": "started"})


@app.get("/api/refresh/status")
async def api_refresh_status():
    return JSONResponse({"running": _refresh_running})


async def _run_refresh():
    """Background-Task: Sammelt alle Daten neu und schreibt Cache (parallel)."""
    global _refresh_running
    import time
    start = time.monotonic()
    try:
        logger.info("Background-Refresh gestartet (parallel)...")
        from src.data.market import collect_all_market_data, get_all_tickers, load_portfolio as load_port
        from src.data.macro import collect_all_macro_data
        from src.data.calendar import fetch_earnings_calendar, get_market_status, get_upcoming_macro_events
        from src.data.news import collect_all_news
        import json

        settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
        with open(settings_path) as f:
            settings = json.load(f)

        portfolio = load_port()
        # Ticker-Liste direkt aus dem Portfolio ableiten, damit Calendar/News
        # nicht auf Market-Daten warten müssen.
        portfolio_tickers = get_all_tickers(portfolio)
        fred_key = settings.get("fred", {}).get("api_key", "")
        brave_key = settings.get("brave_search", {}).get("api_key", "")
        finnhub_key = settings.get("finnhub", {}).get("api_key", "")

        async def run_market():
            data = await asyncio.to_thread(collect_all_market_data, portfolio)
            save_cache("market_data", data)
            return data

        async def run_macro():
            data = await asyncio.to_thread(collect_all_macro_data, fred_key)
            save_cache("macro_data", data)
            return data

        async def run_calendar():
            earnings = await asyncio.to_thread(fetch_earnings_calendar, portfolio_tickers)
            market_status = get_market_status()
            macro_events = get_upcoming_macro_events(days_ahead=30)
            save_cache("calendar_data", {
                "earnings": earnings,
                "market_status": market_status,
                "macro_events": macro_events,
            })

        async def run_news():
            if not (brave_key or finnhub_key):
                return
            try:
                data = await asyncio.to_thread(collect_all_news, portfolio_tickers, brave_key, finnhub_key)
                save_cache("news_data", data)
                logger.info("News-Daten gesammelt und gecacht")
            except Exception as e:
                logger.error(f"News-Collection Fehler: {e}")

        results = await asyncio.gather(
            run_market(), run_macro(), run_calendar(), run_news(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Refresh-Teil-Task Fehler: {r}")

        # Monats-Snapshot anlegen, falls fuer aktuellen Monat noch keiner existiert.
        # Damit baut sich die Asset-History-Kurve auch ohne erfolgreichen Monthly-
        # Cron-Job auf — der lief auf manchen Setups wg. Permission/Owner-Issues
        # nicht durch (siehe Commit 95a6d5f), und der Dashboard-Chart blieb leer.
        try:
            market_result = results[0] if results else None
            market_data = market_result if isinstance(market_result, dict) else get_market_data()
            overview = compute_portfolio_overview(portfolio, market_data)
            _maybe_append_monthly_snapshot(overview)
        except Exception as e:
            logger.error(f"Snapshot-Append fehlgeschlagen: {e}")

        logger.info(f"Background-Refresh abgeschlossen in {time.monotonic() - start:.1f}s")
    except Exception as e:
        logger.error(f"Background-Refresh Fehler: {e}")
    finally:
        _refresh_running = False


def run_web_server(host: str = "0.0.0.0", port: int = 8080):
    """Startet den Uvicorn Web-Server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, workers=1, log_level="warning")
