#!/usr/bin/env python3
"""
Velora — Interactive Setup Wizard
Guides the user through initial configuration.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"

LANGUAGES = {
    "de": {"name": "Deutsch", "greeting": "Willkommen bei Velora!"},
    "en": {"name": "English", "greeting": "Welcome to Velora!"},
}

COUNTRIES = {
    "AT": {"name": "Austria (Österreich)", "tax": "KESt 27.5%", "tax_rate": 0.275, "currency": "EUR"},
    "DE": {"name": "Germany (Deutschland)", "tax": "Abgeltungssteuer 26.375%", "tax_rate": 0.26375, "currency": "EUR"},
    "CH": {"name": "Switzerland (Schweiz)", "tax": "Verrechnungssteuer 35%", "tax_rate": 0.35, "currency": "CHF"},
    "US": {"name": "United States", "tax": "Capital Gains Tax (varies)", "tax_rate": 0.20, "currency": "USD"},
    "UK": {"name": "United Kingdom", "tax": "Capital Gains Tax 20%", "tax_rate": 0.20, "currency": "GBP"},
    "OTHER": {"name": "Other", "tax": "Configure manually", "tax_rate": 0.0, "currency": "EUR"},
}

BANNER = """
\033[1;36m
    ██╗   ██╗███████╗██╗      ██████╗ ██████╗  █████╗
    ██║   ██║██╔════╝██║     ██╔═══██╗██╔══██╗██╔══██╗
    ██║   ██║█████╗  ██║     ██║   ██║██████╔╝███████║
    ╚██╗ ██╔╝██╔══╝  ██║     ██║   ██║██╔══██╗██╔══██║
     ╚████╔╝ ███████╗███████╗╚██████╔╝██║  ██║██║  ██║
      ╚═══╝  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
\033[0m
    \033[90mYour AI-powered personal wealth advisor\033[0m
"""


def clear():
    os.system("clear" if os.name != "nt" else "cls")


def header(title: str):
    clear()
    print(BANNER)
    print(f"\033[1;37m  ── {title} ──\033[0m\n")


def ask(prompt: str, default: str = None) -> str:
    suffix = f" [{default}]" if default else ""
    result = input(f"  \033[1;33m→\033[0m {prompt}{suffix}: ").strip()
    return result if result else (default or "")


def ask_choice(prompt: str, options: dict) -> str:
    print(f"  \033[1;33m→\033[0m {prompt}\n")
    keys = list(options.keys())
    for i, (key, val) in enumerate(options.items(), 1):
        name = val if isinstance(val, str) else val.get("name", key)
        print(f"    \033[36m{i})\033[0m {name}")
    print()
    while True:
        choice = input(f"  \033[1;33m→\033[0m Choose (1-{len(keys)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            if choice in keys:
                return choice
        print(f"    \033[31mInvalid choice. Enter 1-{len(keys)}.\033[0m")


def ask_yn(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    result = input(f"  \033[1;33m→\033[0m {prompt} ({d}): ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes", "ja", "j")


def check_prerequisites():
    """Check Python, Claude CLI, etc."""
    header("Prerequisites Check")
    errors = []

    # Python version
    v = sys.version_info
    if v.major == 3 and v.minor >= 11:
        print(f"  \033[32m✓\033[0m Python {v.major}.{v.minor}.{v.micro}")
    else:
        errors.append(f"Python 3.11+ required, found {v.major}.{v.minor}")
        print(f"  \033[31m✗\033[0m Python {v.major}.{v.minor} (need 3.11+)")

    # Claude CLI
    claude_path = shutil.which("claude")
    if claude_path:
        print(f"  \033[32m✓\033[0m Claude Code CLI found")
    else:
        print(f"  \033[31m✗\033[0m Claude Code CLI not found")
        errors.append("Claude Code CLI not installed. Run: npm install -g @anthropic-ai/claude-code")

    # pip
    pip_path = shutil.which("pip3") or shutil.which("pip")
    if pip_path:
        print(f"  \033[32m✓\033[0m pip found")
    else:
        errors.append("pip not found")
        print(f"  \033[31m✗\033[0m pip not found")

    if errors:
        print(f"\n  \033[31mPlease fix these issues before continuing:\033[0m")
        for e in errors:
            print(f"    • {e}")
        if not ask_yn("Continue anyway?", False):
            sys.exit(1)

    print()
    input("  Press Enter to continue...")


def setup_language() -> str:
    header("Language / Sprache")
    lang = ask_choice("Select your language:", {k: v["name"] for k, v in LANGUAGES.items()})
    return lang


def setup_country() -> dict:
    header("Country & Tax Regime")
    country = ask_choice("Select your country:", {k: v["name"] for k, v in COUNTRIES.items()})
    return {"code": country, **COUNTRIES[country]}


def setup_channels() -> dict:
    """Welche Wege Velora nutzt. Das Web-Dashboard läuft immer; alles andere ist optional
    und lässt sich später in config/settings.json nachtragen."""
    header("Apps & Notifications")
    print("  The \033[1mweb dashboard\033[0m is always on (browser; installable as an app on your phone).")
    print("  Everything below is optional and can be added later in config/settings.json.\n")

    channels: dict = {"telegram": {}, "web_push": {}, "apns": {}}

    print("  \033[1mTelegram\033[0m – briefings as messages + chat with Velora from Telegram.")
    if ask_yn("Use Telegram?", False):
        channels["telegram"] = setup_telegram()

    print("\n  \033[1mBrowser push\033[0m – notifications from the web dashboard (needs HTTPS or localhost).")
    if ask_yn("Enable browser push notifications?", False):
        channels["web_push"] = {"contact": ask("Contact e-mail for the push services", "you@example.com")}

    print("\n  \033[1miOS app\033[0m – build it yourself from ios/ (see ios/README.md). Works with a free")
    print("  Apple account; push notifications need a paid Apple Developer account + an APNs key.")
    if ask_yn("Set up iOS push notifications now (paid Apple Developer account)?", False):
        channels["apns"] = {
            "key_path": ask("Path to the APNs key (.p8)", "config/keys/AuthKey_XXXXXXXXXX.p8"),
            "key_id": ask("Key ID (10 characters)"),
            "team_id": ask("Team ID (10 characters)"),
            "bundle_id": ask("Bundle ID of your app build", "com.example.velora"),
        }
    return channels


def setup_vapid(contact: str) -> dict:
    """Erzeugt VAPID-Schlüssel für Browser-Push mit dem frisch installierten venv."""
    venv_python = Path(__file__).parent / "venv" / "bin" / "python"
    result = subprocess.run([str(venv_python), "scripts/generate_vapid.py", contact],
                            capture_output=True, text=True, check=True)
    keys = {}
    for line in result.stdout.splitlines():
        name, _, value = line.partition("=")
        keys[name] = value.strip('"').replace("\\n", "\n")
    return {
        "vapid_public_key": keys.get("VAPID_PUBLIC_KEY", ""),
        "vapid_private_key": keys.get("VAPID_PRIVATE_KEY", ""),
        "vapid_subject": keys.get("VAPID_SUBJECT", f"mailto:{contact}"),
    }


def setup_telegram() -> dict:
    header("Telegram Bot Setup")
    print("  To create a Telegram bot:\n")
    print("  1. Open Telegram and search for \033[1m@BotFather\033[0m")
    print("  2. Send \033[1m/newbot\033[0m and follow the instructions")
    print("  3. Copy the bot token")
    print("  4. Start a chat with your bot and send any message")
    print("  5. Get your chat ID from: https://api.telegram.org/bot<TOKEN>/getUpdates\n")

    token = ask("Bot Token")
    chat_id = ask("Your Chat ID")
    return {"bot_token": token, "chat_id": chat_id}


def setup_apis() -> dict:
    header("API Keys (optional)")
    apis = {}

    print("  These APIs improve the quality of briefings but are optional.\n")

    if ask_yn("Do you have a Brave Search API key? (for news research)", False):
        apis["brave"] = ask("Brave Search API Key")
    else:
        apis["brave"] = ""

    if ask_yn("Do you have a FRED API key? (for US macro data, free at fred.stlouisfed.org)", False):
        apis["fred"] = ask("FRED API Key")
    else:
        apis["fred"] = ""

    if ask_yn("Do you have a Finnhub API key? (for sentiment & news, free at finnhub.io)", False):
        apis["finnhub"] = ask("Finnhub API Key")
    else:
        apis["finnhub"] = ""

    return apis


def setup_schedule() -> dict:
    header("Briefing Schedule")

    print("  When should Velora send your briefings?\n")
    days_input = ask("Briefing days (comma-separated)", "monday,thursday")
    days = [d.strip().lower() for d in days_input.split(",")]

    time = ask("Briefing time (24h format)", "07:00")

    monthly_day = ask("Monthly report day of month", "1")
    monthly_time = ask("Monthly report time", "09:00")

    return {
        "briefing_days": days,
        "briefing_time": time,
        "monthly_report_day": int(monthly_day),
        "monthly_report_time": monthly_time,
    }


def parse_csv_value(val: str) -> float:
    """Parst einen Wert aus CSV — behandelt €, $, Komma als Dezimal, etc."""
    if not val or not isinstance(val, str):
        return 0.0
    val = val.strip().replace("€", "").replace("$", "").replace("%", "").strip()
    # Deutsches Format: "2.573,26" → "2573.26"
    if "," in val and "." in val:
        val = val.replace(".", "").replace(",", ".")
    elif "," in val:
        val = val.replace(",", ".")
    try:
        return float(val)
    except ValueError:
        return 0.0


def detect_csv_columns(headers: list[str]) -> dict:
    """Erkennt automatisch welche Spalte was ist anhand der Header-Namen."""
    mapping = {}
    header_lower = [h.lower().strip() for h in headers]

    for i, h in enumerate(header_lower):
        if h in ("name", "bezeichnung", "title", "stock"):
            mapping["name"] = i
        elif h in ("isin",):
            mapping["isin"] = i
        elif h in ("stück", "stk", "shares", "quantity", "anzahl", "menge"):
            mapping["shares"] = i
        elif h in ("buy in", "buy_in", "kaufkurs", "einkaufspreis", "avg price", "einstandskurs"):
            mapping["buy_in"] = i
        elif h in ("wert", "value", "marktwert", "current value"):
            mapping["value"] = i
        elif h in ("profit", "gewinn", "p/l", "pnl", "gain/loss"):
            mapping["profit"] = i
        elif h in ("konto-name", "konto", "account", "kontoname"):
            mapping["account_name"] = i
        elif h in ("bank",):
            mapping["bank"] = i
        elif h in ("zinsen", "interest", "zins"):
            mapping["interest"] = i
        elif h in ("notiz", "note", "notes", "bemerkung"):
            mapping["note"] = i

    return mapping


def import_portfolio_csv(csv_path: str, account_name: str) -> list[dict]:
    """Importiert Positionen aus einer CSV-Datei."""
    import csv

    positions = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        col_map = detect_csv_columns(headers)

        if "name" not in col_map and "isin" not in col_map:
            # Versuche Spaltenreihenfolge zu raten
            print(f"    \033[33m⚠\033[0m Could not auto-detect columns. Headers: {headers}")
            return []

        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue

            name = row[col_map["name"]].strip() if "name" in col_map else ""
            isin = row[col_map["isin"]].strip() if "isin" in col_map else ""
            shares = parse_csv_value(row[col_map["shares"]]) if "shares" in col_map else 0
            buy_in = parse_csv_value(row[col_map["buy_in"]]) if "buy_in" in col_map else 0

            if not name and not isin:
                continue
            if shares <= 0:
                continue

            # Währung raten: US-ISIN = USD, sonst EUR
            currency = "USD" if isin.startswith("US") else "EUR"

            positions.append({
                "name": name or isin,
                "isin": isin,
                "ticker": "",  # User muss Ticker manuell hinzufügen oder wir raten
                "shares": shares,
                "buy_in": buy_in,
                "currency": currency,
            })
            print(f"    \033[32m✓\033[0m {shares:.2f}x {name or isin} (Buy-In: {buy_in:.2f})")

    return positions


def import_cash_csv(csv_path: str) -> dict:
    """Importiert Bankkonten aus einer CSV-Datei."""
    import csv

    accounts = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        col_map = detect_csv_columns(headers)

        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue

            name = row[col_map.get("account_name", 0)].strip() if col_map.get("account_name") is not None else row[0].strip()
            bank = row[col_map["bank"]].strip() if "bank" in col_map else ""
            value = parse_csv_value(row[col_map.get("value", col_map.get("account_name", 2))]) if len(row) > 2 else 0

            # Wert-Spalte finden: suche nach der Spalte mit €-Zeichen
            for i, cell in enumerate(row):
                if "€" in cell and i != col_map.get("account_name"):
                    value = parse_csv_value(cell)
                    break

            interest = parse_csv_value(row[col_map["interest"]]) if "interest" in col_map else 0
            note = row[col_map["note"]].strip() if "note" in col_map and col_map["note"] < len(row) else ""

            if not name:
                continue

            key = name.lower().replace(" ", "_").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            is_depot = any(w in name.lower() for w in ["abrechnung", "settlement", "depot", "trade republic cash"])

            accounts[key] = {
                "bank": bank,
                "value": value,
                "interest": interest,
                "note": note,
                "is_depot_cash": is_depot,
            }
            print(f"    \033[32m✓\033[0m {name}: {value:.2f}€ ({bank})")

    return accounts


def setup_portfolio(country: dict, lang: str):
    header("Portfolio Setup")

    mode = ask_choice("How do you want to set up your portfolio?", {
        "csv": "Import from CSV files (recommended)",
        "manual": "Enter positions manually",
        "skip": "Skip — configure later",
    })

    if mode == "skip":
        src = CONFIG_DIR / "portfolio.example.json"
        dst = CONFIG_DIR / "portfolio.json"
        if not dst.exists() and src.exists():
            shutil.copy(src, dst)
        print("\n  \033[90mEdit config/portfolio.json later to add your positions.\033[0m")
        return

    portfolio = {
        "last_updated": "",
        "accounts": {},
        "bank_accounts": {},
        "user_profile": {
            "country": country["code"],
            "tax_regime": country["tax"],
            "risk_tolerance": "medium",
            "goal": "growth",
            "time_horizon": "long_term",
        },
    }

    if mode == "csv":
        print("\n  \033[1mCSV Import\033[0m")
        print("  Supported formats: Trade Republic, Erste Bank, Interactive Brokers,")
        print("  or any CSV with columns: Name, ISIN, Stück/Shares, Buy In\n")

        while True:
            account_name = ask("Broker/account name (e.g. 'trade_republic')")
            if not account_name:
                break

            csv_path = ask("Path to portfolio CSV file")
            if not csv_path or not Path(csv_path).exists():
                print(f"    \033[31mFile not found: {csv_path}\033[0m")
                continue

            print(f"\n  Importing {csv_path}...\n")
            positions = import_portfolio_csv(csv_path, account_name)

            if positions:
                portfolio["accounts"][account_name.lower().replace(" ", "_")] = {"positions": positions}
                print(f"\n  \033[32m✓ Imported {len(positions)} positions for {account_name}\033[0m\n")

                # Ticker-Zuordnung
                print("  \033[33mNote:\033[0m Yahoo Finance tickers need to be added.")
                print("  Edit config/portfolio.json and add tickers (e.g. AAPL, SAP.DE, ASML.AS)\n")
            else:
                print(f"    \033[31mCould not parse CSV. Check the format.\033[0m")

            if not ask_yn("Import another broker account?", False):
                break

        # Cash CSV
        if ask_yn("\nImport bank/cash accounts from CSV?", False):
            csv_path = ask("Path to cash CSV file")
            if csv_path and Path(csv_path).exists():
                print(f"\n  Importing {csv_path}...\n")
                cash_accounts = import_cash_csv(csv_path)
                portfolio["bank_accounts"] = cash_accounts
                print(f"\n  \033[32m✓ Imported {len(cash_accounts)} accounts\033[0m\n")

    elif mode == "manual":
        # Add broker accounts manually
        while True:
            account_name = ask("Broker/account name (e.g. 'interactive_brokers')")
            if not account_name:
                break
            portfolio["accounts"][account_name.lower().replace(" ", "_")] = {"positions": []}

            print(f"\n  Add positions for {account_name} (empty name to finish):\n")
            while True:
                name = ask("  Stock/ETF name")
                if not name:
                    break
                ticker = ask("  Yahoo Finance ticker (e.g. AAPL, SAP.DE)")
                shares = float(ask("  Number of shares", "1"))
                buy_in = float(ask("  Buy-in price per share", "0"))
                currency = ask("  Currency", country["currency"])
                isin = ask("  ISIN (optional)", "")

                portfolio["accounts"][account_name.lower().replace(" ", "_")]["positions"].append({
                    "name": name,
                    "isin": isin,
                    "ticker": ticker,
                    "shares": shares,
                    "buy_in": buy_in,
                    "currency": currency,
                })
                print(f"    \033[32m✓\033[0m Added {shares}x {name}\n")

            if not ask_yn("Add another broker account?", False):
                break

    # Bank accounts (manual, wenn nicht via CSV)
    if not portfolio["bank_accounts"] and ask_yn("\nAdd bank/cash accounts?", False):
        while True:
            name = ask("Account name (e.g. 'savings')")
            if not name:
                break
            bank = ask("Bank name")
            value = float(ask("Current balance", "0"))
            interest = float(ask("Interest rate (%)", "0"))
            is_depot = ask_yn("Is this a depot cash account?", False)

            portfolio["bank_accounts"][name.lower().replace(" ", "_")] = {
                "bank": bank,
                "value": value,
                "interest": interest,
                "note": "",
                "is_depot_cash": is_depot,
            }
            print(f"    \033[32m✓\033[0m Added {name}: {value}€\n")

            if not ask_yn("Add another account?", False):
                break

    with open(CONFIG_DIR / "portfolio.json", "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)


def install_dependencies():
    header("Installing Dependencies")
    venv_path = Path(__file__).parent / "venv"

    if not venv_path.exists():
        print("  Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)

    pip = str(venv_path / "bin" / "pip")
    print("  Installing packages...\n")
    subprocess.run([pip, "install", "--prefer-binary", "-r", "requirements.txt"], check=True)
    print(f"\n  \033[32m✓\033[0m Dependencies installed")


def save_settings(channels: dict, apis: dict, schedule: dict, country: dict, lang: str):
    settings = {
        "telegram": channels["telegram"],
        "web_push": channels["web_push"],
        "apns": channels["apns"],
        "brave_search": {"api_key": apis.get("brave", "")},
        "fred": {"api_key": apis.get("fred", "")},
        "finnhub": {"api_key": apis.get("finnhub", "")},
        "schedule": schedule,
        "claude": {
            "command": "claude",
            "flags": ["--print"],
            "timeout": 1200,
        },
        "data": {
            "primary_source": "yfinance",
            "fallback_source": "twelvedata",
            "twelvedata_api_key": "",
        },
        "user": {
            "language": lang,
            "country": country["code"],
            "tax_regime": country["tax"],
            "tax_rate": country["tax_rate"],
        },
        "web": {
            "host": "0.0.0.0",
            "port": 8080,
        },
    }

    with open(CONFIG_DIR / "settings.json", "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def show_summary(channels: dict, apis: dict, schedule: dict, country: dict, lang: str):
    telegram = channels["telegram"]
    header("Setup Complete!")
    print(f"  \033[32m✓\033[0m Language: {LANGUAGES[lang]['name']}")
    print(f"  \033[32m✓\033[0m Country: {country['name']} ({country['tax']})")
    print(f"  \033[32m✓\033[0m Web dashboard: on")
    print(f"  \033[32m✓\033[0m Telegram: {'configured' if telegram.get('bot_token') else 'off'}")
    print(f"  \033[32m✓\033[0m Browser push: {'configured' if channels['web_push'].get('vapid_public_key') else 'off'}")
    print(f"  \033[32m✓\033[0m iOS push: {'configured' if channels['apns'].get('key_id') else 'off'}")
    print(f"  \033[32m✓\033[0m Brave Search: {'configured' if apis.get('brave') else 'not configured'}")
    print(f"  \033[32m✓\033[0m FRED API: {'configured' if apis.get('fred') else 'not configured'}")
    print(f"  \033[32m✓\033[0m Briefings: {', '.join(schedule['briefing_days'])} at {schedule['briefing_time']}")
    print()
    print("  \033[1mNext steps:\033[0m")
    print("  1. Edit \033[1mconfig/portfolio.json\033[0m with your positions (if not done)")
    print("  2. Make sure Claude Code CLI is authenticated: \033[1mclaude --print 'test'\033[0m")
    print("  3. Test a briefing: \033[1m./venv/bin/python -m src.main briefing\033[0m")
    print("  4. Start the Web Dashboard: \033[1m./venv/bin/python -m src.main web\033[0m")
    print(f"     → Open \033[1mhttp://localhost:8080\033[0m in your browser")
    if telegram.get("bot_token"):
        print("  5. Start the Telegram bot: \033[1m./venv/bin/python -m src.main bot\033[0m")
    print("  On a server (Raspberry Pi etc.): \033[1mbash scripts/setup_server.sh\033[0m sets up services + cron.")
    print()
    print("  \033[90mFull documentation: README.md\033[0m")
    print()


def main():
    clear()
    print(BANNER)
    print("  \033[1mInteractive Setup\033[0m\n")
    input("  Press Enter to start...")

    check_prerequisites()
    lang = setup_language()
    country = setup_country()
    channels = setup_channels()
    apis = setup_apis()
    schedule = setup_schedule()

    # Create dirs
    (Path(__file__).parent / "memory").mkdir(exist_ok=True)
    (Path(__file__).parent / "memory" / "cache").mkdir(exist_ok=True)
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)

    web_push_contact = channels["web_push"].pop("contact", None)
    save_settings(channels, apis, schedule, country, lang)
    setup_portfolio(country, lang)
    install_dependencies()
    if web_push_contact:
        channels["web_push"] = setup_vapid(web_push_contact)
        save_settings(channels, apis, schedule, country, lang)
    show_summary(channels, apis, schedule, country, lang)


if __name__ == "__main__":
    main()
