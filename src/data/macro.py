"""
Makro-Daten: US (FRED) + EU (ECB).
Zinsen, Inflation, Arbeitslosigkeit, Yield Curves.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


def _fetch_fred_series(name: str, series_id: str, api_key: str, start: str, today: str,
                       units: str = "lin") -> tuple[str, dict | None]:
    base_url = "https://api.stlouisfed.org/fred/series/observations"
    try:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": today,
            "sort_order": "desc",
            "limit": 5,
            # lin = Rohwert, pc1 = Veränderung zum Vorjahr in % (FRED rechnet serverseitig)
            "units": units,
        }
        resp = requests.get(base_url, params=params, timeout=10)
        data = resp.json()
        observations = data.get("observations", [])
        if observations:
            latest = observations[0]
            value = latest.get("value", ".")
            if value != ".":
                return name, {
                    "value": round(float(value), 3),
                    "date": latest["date"],
                    "source": f"FRED:{series_id}" + (f" ({units})" if units != "lin" else ""),
                }
    except Exception as e:
        logger.error(f"FRED {name} ({series_id}) Fehler: {e}")
    return name, None


def fetch_fred_data(api_key: str) -> dict:
    """Holt wichtige US-Makrodaten von FRED (parallel)."""
    series = {
        "fed_funds_rate": "FEDFUNDS",
        # CPIAUCSL ist ein Indexstand (~320) — als YoY-Rate nur mit units=pc1
        "us_cpi_yoy": ("CPIAUCSL", "pc1"),
        "us_10y_yield": "DGS10",
        "us_2y_yield": "DGS2",
        "us_unemployment": "UNRATE",
        "us_gdp_growth": "A191RL1Q225SBEA",
        "vix": "VIXCLS",
        "credit_spread_hy": "BAMLH0A0HYM2",
    }

    results = {}
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    with ThreadPoolExecutor(max_workers=min(8, len(series))) as ex:
        futures = []
        for name, spec in series.items():
            sid, units = spec if isinstance(spec, tuple) else (spec, "lin")
            futures.append(ex.submit(_fetch_fred_series, name, sid, api_key, start, today, units))
        for fut in as_completed(futures):
            name, data = fut.result()
            if data:
                results[name] = data

    # Yield Curve Spread berechnen
    if "us_10y_yield" in results and "us_2y_yield" in results:
        spread = results["us_10y_yield"]["value"] - results["us_2y_yield"]["value"]
        results["yield_curve_spread"] = {
            "value": round(spread, 3),
            "date": results["us_10y_yield"]["date"],
            "source": "berechnet aus FRED:DGS10 - FRED:DGS2",
            "note": "negativ = invertiert = Rezessionssignal",
        }

    return results


def _fetch_ecb_endpoint(name: str, url: str, desc: str) -> tuple[str, dict | None]:
    headers = {"Accept": "application/vnd.sdmx.data+json;version=1.0.0-wd"}
    try:
        resp = requests.get(url, headers=headers, params={"lastNObservations": "1"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            datasets = data.get("dataSets", [{}])
            if datasets:
                series = datasets[0].get("series", {})
                for _, s in series.items():
                    obs = s.get("observations", {})
                    if obs:
                        last_key = max(obs.keys())
                        value = obs[last_key][0]
                        return name, {
                            "value": float(value),
                            "description": desc,
                            "source": "ECB Data API",
                            "timestamp": datetime.now().isoformat(),
                        }
    except Exception as e:
        logger.error(f"ECB {name} Fehler: {e}")
    return name, None


def fetch_ecb_data() -> dict:
    """Holt EZB-Daten direkt von der ECB Data API (parallel)."""
    endpoints = {
        "ecb_main_rate": {
            "url": "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.4F.KR.MRR_FR.LEV",
            "desc": "EZB Hauptrefinanzierungssatz",
        },
        "eu_hicp_inflation": {
            "url": "https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR",
            "desc": "HICP Inflation Eurozone YoY",
        },
        "eur_usd": {
            "url": "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
            "desc": "EUR/USD Wechselkurs",
        },
    }

    results = {}
    with ThreadPoolExecutor(max_workers=len(endpoints)) as ex:
        futures = [ex.submit(_fetch_ecb_endpoint, name, ep["url"], ep["desc"]) for name, ep in endpoints.items()]
        for fut in as_completed(futures):
            name, data = fut.result()
            if data:
                results[name] = data
    return results


def fetch_fear_greed() -> dict | None:
    """CNN Fear & Greed Index."""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        return {
            "value": fg.get("score"),
            "rating": fg.get("rating"),
            "previous_close": fg.get("previous_close"),
            "previous_1_week": fg.get("previous_1_week"),
            "previous_1_month": fg.get("previous_1_month"),
            "previous_1_year": fg.get("previous_1_year"),
            "source": "CNN Fear & Greed Index",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Fear & Greed Fehler: {e}")
        return None


def collect_all_macro_data(fred_api_key: str) -> dict:
    """Sammelt alle Makrodaten (FRED + ECB + Fear&Greed parallel)."""
    with ThreadPoolExecutor(max_workers=3) as ex:
        fred_future = ex.submit(fetch_fred_data, fred_api_key) if fred_api_key else None
        ecb_future = ex.submit(fetch_ecb_data)
        fg_future = ex.submit(fetch_fear_greed)

        fred = fred_future.result() if fred_future else {}
        ecb = ecb_future.result()
        fear_greed = fg_future.result()

    return {
        "us": fred,
        "eu": ecb,
        "fear_greed": fear_greed,
        "collected_at": datetime.now().isoformat(),
    }
