"""
Marktdaten: Kurse, Fundamentals, Insider-Transaktionen.
Primär yfinance, Fallback Twelve Data.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_portfolio() -> dict:
    with open(CONFIG_DIR / "portfolio.json") as f:
        return json.load(f)


def load_watchlist() -> dict:
    with open(CONFIG_DIR / "watchlist.json") as f:
        return json.load(f)


def get_all_tickers(portfolio: dict) -> list[dict]:
    """Extrahiert alle einzigartigen Ticker aus dem Portfolio."""
    tickers = []
    seen = set()
    for account_name, account in portfolio["accounts"].items():
        for pos in account["positions"]:
            ticker = pos.get("ticker")
            if ticker and ticker not in seen:
                seen.add(ticker)
                tickers.append({
                    "ticker": ticker,
                    "name": pos["name"],
                    "isin": pos["isin"],
                    "currency": pos["currency"],
                })
    return tickers


def validate_price(price, ticker: str, field: str) -> float | None:
    """Validiert dass ein Preis plausibel ist."""
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        logger.warning(f"Ungültiger Preis für {ticker}.{field}: {price}")
        return None
    if price <= 0 or price > 1_000_000:
        logger.warning(f"Unplausibler Preis für {ticker}.{field}: {price}")
        return None
    return price


def validate_ratio(value, ticker: str, field: str, min_val: float = -1000, max_val: float = 10000) -> float | None:
    """Validiert dass eine Kennzahl plausibel ist."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value < min_val or value > max_val:
        logger.warning(f"Unplausible Kennzahl für {ticker}.{field}: {value}")
        return None
    return round(value, 4)


def _build_price_dict(ticker: str, info: dict, hist_1y) -> dict | None:
    """Baut Price-Dict aus info + 1y-History. Gibt None zurück wenn kein valider Kurs."""
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
    if not current_price and hist_1y is not None and not hist_1y.empty:
        current_price = float(hist_1y["Close"].iloc[-1])

    current_price = validate_price(current_price, ticker, "current_price")
    if not current_price:
        return None

    prev_close = validate_price(info.get("previousClose"), ticker, "prev_close")
    week_52_high = validate_price(info.get("fiftyTwoWeekHigh"), ticker, "52w_high")
    week_52_low = validate_price(info.get("fiftyTwoWeekLow"), ticker, "52w_low")

    # 1m/6m/1y aus 1y-History slicen statt separate Calls
    perf_1m = perf_6m = perf_1y = None
    if hist_1y is not None and not hist_1y.empty:
        closes = hist_1y["Close"]
        n = len(closes)
        if n >= 50:
            perf_1y = (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100
        if n >= 20:
            start_6m = max(0, n - 126)  # ~126 Handelstage ≈ 6 Monate
            if n - start_6m >= 20:
                perf_6m = (float(closes.iloc[-1]) / float(closes.iloc[start_6m]) - 1) * 100
        if n >= 5:
            start_1m = max(0, n - 21)  # ~21 Handelstage ≈ 1 Monat
            if n - start_1m >= 5:
                perf_1m = (float(closes.iloc[-1]) / float(closes.iloc[start_1m]) - 1) * 100

    # Cross-Validation: 52W-Range nur prüfen wenn beide Werte plausibel auseinanderliegen
    if week_52_high and week_52_low and current_price:
        range_spread = (week_52_high - week_52_low) / week_52_low if week_52_low > 0 else 0
        if range_spread > 0.02:
            if current_price > week_52_high * 1.10 or current_price < week_52_low * 0.90:
                logger.warning(f"{ticker}: Kurs {current_price} außerhalb 52W-Range [{week_52_low}-{week_52_high}] — 52W-Daten möglicherweise veraltet")
                week_52_high = None
                week_52_low = None

    return {
        "ticker": ticker,
        "current_price": current_price,
        "currency": info.get("currency"),
        "previous_close": prev_close,
        "change_pct": round((current_price / prev_close - 1) * 100, 2) if current_price and prev_close else None,
        "52w_high": week_52_high,
        "52w_low": week_52_low,
        "perf_1m_pct": round(perf_1m, 2) if perf_1m is not None else None,
        "perf_6m_pct": round(perf_6m, 2) if perf_6m is not None else None,
        "perf_1y_pct": round(perf_1y, 2) if perf_1y is not None else None,
        "market_cap": info.get("marketCap"),
        "pe_ratio": validate_ratio(info.get("trailingPE"), ticker, "pe", -100, 5000),
        "forward_pe": validate_ratio(info.get("forwardPE"), ticker, "fwd_pe", -1000, 5000),
        "peg_ratio": validate_ratio(info.get("pegRatio"), ticker, "peg", -50, 100),
        "price_to_book": validate_ratio(info.get("priceToBook"), ticker, "pb", 0, 500),
        "dividend_yield": validate_ratio(info.get("dividendYield"), ticker, "div", 0, 50),
        "beta": validate_ratio(info.get("beta"), ticker, "beta", -5, 10),
        "short_interest": validate_ratio(info.get("shortPercentOfFloat"), ticker, "short", 0, 1),
        "insider_buy_pct": validate_ratio(info.get("heldPercentInsiders"), ticker, "insider", 0, 1),
        "institutional_pct": validate_ratio(info.get("heldPercentInstitutions"), ticker, "inst", 0, 1),
        "free_cash_flow": info.get("freeCashflow"),
        "revenue_growth": validate_ratio(info.get("revenueGrowth"), ticker, "rev_growth", -1, 100),
        "profit_margin": validate_ratio(info.get("profitMargins"), ticker, "margin", -10, 1),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "source": "yfinance",
        "timestamp": datetime.now().isoformat(),
    }


def fetch_price_data(ticker: str, retries: int = 2) -> dict | None:
    """Holt aktuelle Kursdaten + Key Stats für einen Ticker. Mit Retry-Logik."""
    for attempt in range(retries + 1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist_1y = stock.history(period="1y")
            result = _build_price_dict(ticker, info, hist_1y)
            if result is None:
                if attempt < retries:
                    logger.info(f"Retry {attempt+1} für {ticker}...")
                    continue
                logger.error(f"Kein valider Kurs für {ticker} nach {retries+1} Versuchen")
                return None
            return result
        except Exception as e:
            if attempt < retries:
                logger.info(f"Retry {attempt+1} für {ticker} nach Fehler: {e}")
                continue
            logger.error(f"Fehler beim Abrufen von {ticker}: {e}")
            return None


def _extract_insiders(stock, ticker: str) -> list[dict]:
    """Extrahiert Insider-Transaktionen aus einer yf.Ticker-Instanz."""
    try:
        insiders = stock.insider_transactions
        if insiders is None or insiders.empty:
            return []
        recent = []
        for _, row in insiders.head(10).iterrows():
            recent.append({
                "insider": str(row.get("Insider", "")),
                "relation": str(row.get("Relation", "")),
                "transaction": str(row.get("Transaction", "")),
                "shares": row.get("Shares", 0),
                "value": row.get("Value", 0),
                "date": str(row.get("Date", "")),
            })
        return recent
    except Exception as e:
        logger.error(f"Insider-Daten für {ticker} Fehler: {e}")
        return []


def fetch_ticker_bundle(ticker: str, retries: int = 2) -> tuple[dict | None, list[dict]]:
    """Holt Price + Insider gemeinsam (teilt yf.Ticker-Instanz)."""
    for attempt in range(retries + 1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist_1y = stock.history(period="1y")
            price = _build_price_dict(ticker, info, hist_1y)
            if price is None:
                if attempt < retries:
                    logger.info(f"Retry {attempt+1} für {ticker}...")
                    continue
                logger.error(f"Kein valider Kurs für {ticker} nach {retries+1} Versuchen")
                return None, []
            insiders = _extract_insiders(stock, ticker)
            return price, insiders
        except Exception as e:
            if attempt < retries:
                logger.info(f"Retry {attempt+1} für {ticker} nach Fehler: {e}")
                continue
            logger.error(f"Fehler beim Abrufen von {ticker}: {e}")
            return None, []
    return None, []


def _fetch_single_index(name: str, ticker: str) -> tuple[str, dict | None]:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return name, None
        current = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[0])
        return name, {
            "value": round(current, 2),
            "change_pct": round((current / prev - 1) * 100, 2),
            "source": "yfinance",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Index {name} ({ticker}) Fehler: {e}")
        return name, None


def fetch_index_data() -> dict:
    """Holt Daten für wichtige Indizes (parallel)."""
    indices = {
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DAX": "^GDAXI",
        "ATX": "^ATX",
        "Euro Stoxx 50": "^STOXX50E",
        "VIX": "^VIX",
        "Gold": "GC=F",
        "EUR/USD": "EURUSD=X",
        "BTC/USD": "BTC-USD",
    }
    results = {}
    with ThreadPoolExecutor(max_workers=min(10, len(indices))) as ex:
        futures = [ex.submit(_fetch_single_index, name, tk) for name, tk in indices.items()]
        for fut in as_completed(futures):
            name, data = fut.result()
            if data:
                results[name] = data
    return results


def fetch_insider_activity(ticker: str) -> list[dict]:
    """Holt Insider-Transaktionen der letzten 3 Monate."""
    try:
        stock = yf.Ticker(ticker)
        insiders = stock.insider_transactions
        if insiders is None or insiders.empty:
            return []
        recent = []
        cutoff = datetime.now() - timedelta(days=90)
        for _, row in insiders.head(10).iterrows():
            recent.append({
                "insider": str(row.get("Insider", "")),
                "relation": str(row.get("Relation", "")),
                "transaction": str(row.get("Transaction", "")),
                "shares": row.get("Shares", 0),
                "value": row.get("Value", 0),
                "date": str(row.get("Date", "")),
            })
        return recent
    except Exception as e:
        logger.error(f"Insider-Daten für {ticker} Fehler: {e}")
        return []


def collect_all_market_data(portfolio: dict) -> dict:
    """Sammelt alle Marktdaten für das gesamte Portfolio — parallel via ThreadPool."""
    tickers = get_all_tickers(portfolio)
    watchlist = load_watchlist()
    watchlist_items = [item for item in watchlist.get("watchlist", []) if item.get("ticker")]

    positions_data = {}
    watchlist_data = {}

    # Alle Ticker-Fetches (Portfolio + Watchlist + Indizes) parallel
    total = len(tickers) + len(watchlist_items) + 9  # 9 = Anzahl Indizes
    max_workers = min(12, max(1, total))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        pos_futures = {
            ex.submit(fetch_ticker_bundle, t["ticker"]): t
            for t in tickers
        }
        wl_futures = {
            ex.submit(fetch_price_data, item["ticker"]): item
            for item in watchlist_items
        }
        idx_future = ex.submit(fetch_index_data)

        for fut in as_completed(pos_futures):
            t = pos_futures[fut]
            price_data, insider_data = fut.result()
            if price_data:
                positions_data[t["ticker"]] = {
                    **t,
                    "price": price_data,
                    "insiders": insider_data,
                }

        for fut in as_completed(wl_futures):
            item = wl_futures[fut]
            price_data = fut.result()
            if price_data:
                watchlist_data[item["ticker"]] = {
                    "ticker": item["ticker"],
                    "name": item.get("name", item["ticker"]),
                    "price": price_data,
                }

        indices = idx_future.result()

    return {
        "positions": positions_data,
        "watchlist": watchlist_data,
        "indices": indices,
        "collected_at": datetime.now().isoformat(),
    }
