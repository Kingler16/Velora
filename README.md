```
    ██╗   ██╗███████╗██╗      ██████╗ ██████╗  █████╗
    ██║   ██║██╔════╝██║     ██╔═══██╗██╔══██╗██╔══██╗
    ██║   ██║█████╗  ██║     ██║   ██║██████╔╝███████║
    ╚██╗ ██╔╝██╔══╝  ██║     ██║   ██║██╔══██╗██╔══██║
     ╚████╔╝ ███████╗███████╗╚██████╔╝██║  ██║██║  ██║
      ╚═══╝  ╚══════╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
```

**Your AI-powered personal wealth advisor.** Automated portfolio monitoring, market analysis, and investment briefings — on a self-hosted web dashboard, with an optional iOS app and optional Telegram bot.

Runs on Claude Code with your existing Max/Pro subscription — zero API costs for AI.

---

## What It Does

Twice a week, Velora collects market data for your entire portfolio, pulls macroeconomic indicators, searches for relevant news, and feeds everything into Claude Opus with a specialized financial analyst system prompt. The result is a comprehensive briefing on a professional dark-themed web dashboard — and, if you want, as a notification on your phone or a Telegram message. Like having a CFA on retainer.

## Features

| Category | Highlights |
|----------|------------|
| **Web Dashboard** | Dashboard, Portfolio (incl. performance & tax), Market, Briefings, Recommendations, Strategy, Look-through, Chat, Settings. Dark theme, responsive, installable as an app (PWA), multi-language (de/en) |
| **AI Chat** | Talk to Velora about your portfolio in the browser or the iOS app; it can log trades and orders after your confirmation |
| **iOS App** *(optional)* | Native SwiftUI app you build yourself — free Apple account works, push notifications with a paid developer account |
| **Telegram Bot** *(optional)* | Briefings, trade logging (natural language), ticker analysis, free-form chat, watchlist |
| **AI Analysis** | Bi-weekly briefings, monthly reports, on-demand deep-dives, persistent memory across sessions |
| **Portfolio Tracking** | Multi-account, multi-currency (EUR/USD), tax-loss harvesting, benchmark comparison |
| **Recommendations** | BUY/SELL/WATCH tracking, automatic outcome detection, hit-rate stats, trade auto-close |
| **Data Sources** | yfinance, FRED, ECB, Brave Search, Bloomberg RSS, Finnhub, CNN Fear & Greed |
| **Deployment** | Runs on Raspberry Pi (~90MB RAM), systemd auto-start, cron scheduling |

## Example Briefing

```
MARKTLAGE

Relief-Rally (NASDAQ +4.4%, VIX -22%) ändert nichts am Extreme-Fear-Regime.
Yield Curve normal (+52bps), aber Credit Spreads weiten sich.

PORTFOLIO-CHECK

ASML: Stärkster Gewinner (+63% total), aber underperformed am Rally-Tag.
Stop-Loss bei 1050 EUR empfohlen vor Earnings am 15.4.

Gold ETC: -1.8% in EUR trotz +3.4% Goldpreis in USD — der EUR/USD-Effekt.

EMPFEHLUNGEN

Keine neuen Trades. 14 von 17 Positionen reporten in den nächsten 6 Wochen.
Cash-Quote von 31% ist im Extreme-Fear-Umfeld eine Stärke. Abwarten.
```

## Choose How You Use It

The web dashboard is always there. Everything else is optional — mix as you like:

| Channel | What you get | What you need |
|---|---|---|
| **Web dashboard** | Everything: portfolio, briefings, recommendations, chat, settings. Add to home screen on your phone. | Nothing extra |
| **Browser push** | Notifications from the web app (briefings, trades, chat replies, errors) | HTTPS or localhost; VAPID keys (the setup wizard generates them) |
| **Telegram** | Briefings as messages, chat and trade logging from Telegram | A bot from [@BotFather](https://t.me/BotFather) |
| **iOS app** | Native app for your server, works offline with the last state | Mac with Xcode. Free Apple account (reinstall every 7 days) or paid Developer Program (TestFlight) — see [ios/README.md](ios/README.md) |
| **iOS push** | Notifications on your iPhone | Paid Apple Developer Program + APNs key |

The setup wizard asks which channels you want. Which events notify you (briefings, trades, chat replies, system errors, …) can be switched per category on the web settings page or in the iOS app. If a system error can't be delivered as a notification, Velora falls back to Telegram when it's configured.

## Quick Start

```bash
git clone https://github.com/Kingler16/velora.git
cd velora

python3 setup.py          # Interactive setup wizard (creates venv + config)

./venv/bin/python -m src.main briefing   # First AI briefing
./venv/bin/python -m src.main web        # Web dashboard → http://localhost:8080
./venv/bin/python -m src.main bot        # Telegram bot (only if you set it up)
```

The setup wizard guides you through: language, country & tax regime, notification channels, API keys, briefing schedule, and portfolio import (CSV or manual).

Your data stays on your machine: `config/settings.json`, `config/portfolio.json`, `memory/` and `config/keys/` are gitignored.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` (requires Claude Max or Pro)
- Optional: Telegram bot, [Brave Search API](https://brave.com/search/api/), [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html), [Finnhub API](https://finnhub.io/) (all free tier)
- Optional for the iOS app: Mac with Xcode + [XcodeGen](https://github.com/yonaskolb/XcodeGen)

## Web Dashboard

Built with FastAPI + Jinja2 + HTMX + Chart.js + TradingView Lightweight Charts. No Node.js needed.

| Page | What It Shows |
|------|---------------|
| **Dashboard** | KPI cards, allocation donut, portfolio history chart, sortable holdings table, index ticker bar |
| **Portfolio** | Per-account breakdown, currency/sector charts, bank accounts, trade logging modal |
| **Portfolio › Performance / Tax** | Benchmark comparison, monthly returns heatmap, tax-loss harvesting, top/bottom performers |
| **Market** | 9 indices with descriptions, US/EU macro data, Fear & Greed gauge, earnings calendar |
| **Briefings** | Market regime, key insights, expandable briefing history with full text |
| **Recommendations** | Active BUY/SELL cards, WATCH/HOLD watchlist, one-click close, hit-rate KPIs |
| **Strategy** | Optional investment mandate (target allocation, hard rules) and drift against it |
| **Chat** | Conversation with Velora about your portfolio; write actions need your confirmation |
| **Settings** | API keys, language (de/en), briefing schedule, notifications per category |

Start with `python -m src.main web` and open `http://localhost:8080`.

## Telegram Bot (optional)

| Input | Action |
|-------|--------|
| `/status` | Portfolio overview |
| `/briefing` | Trigger AI briefing |
| `/log` | Step-by-step trade form |
| `AAPL` | Deep-dive ticker analysis |
| `watch RKLB` / `unwatch RKLB` | Manage watchlist |
| `Bought 10 AAPL @ 180` | Log a trade (natural language, de/en) |
| *Any text* | Chat with your AI advisor |

Trades logged via Telegram or the web dashboard automatically close matching AI recommendations.

## Architecture

```
[Cron / Telegram / Web Refresh]
        │
        ▼
    main.py ─── data/market.py    → yfinance
        │   ├── data/macro.py     → FRED + ECB + Fear & Greed
        │   ├── data/news.py      → Brave + Bloomberg + Finnhub
        │   └── data/calendar.py  → Earnings + events
        │
        ├──→ cache.py → memory/cache/  → Web Dashboard (FastAPI)
        │
        ▼
    analysis/claude.py → Claude Code CLI (Opus, high effort)
        │
        ▼
    memory.py → briefings, recommendations, theses
        │
        └──→ delivery → web dashboard / browser push / iOS push (APNs) / Telegram
```

### How Claude Is Used

Velora does **not** call the Claude API directly. It shells out to [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) in `--print` mode — no API key needed, uses your Max/Pro subscription, Opus model with high effort, prompts via stdin.

## Running Modes

```bash
python -m src.main briefing              # Bi-weekly briefing (for cron)
python -m src.main monthly               # Monthly report (for cron)
python -m src.main analyze --ticker AAPL  # On-demand analysis
python -m src.main bot                    # Telegram bot (long-running, optional)
python -m src.main web                    # Web dashboard (long-running)
python -m src.main web --port 3000       # Custom port
```

## Configuration

All settings configurable via the web dashboard Settings page or `config/settings.json`:

| Key | Description |
|-----|-------------|
| `telegram.bot_token` | Bot token from @BotFather (optional) |
| `telegram.chat_id` | Your Telegram chat ID (optional) |
| `web_push.*` | VAPID keys for browser push (`python scripts/generate_vapid.py you@example.com`) |
| `apns.*` | iOS push: `key_path`, `key_id`, `team_id`, `bundle_id` — see [ios/README.md](ios/README.md) |
| `app_store_connect.*` | Optional API key so `ios/testflight.sh` waits for build processing |
| `web.auth_token` | Optional password for dashboard and app (recommended if reachable beyond your home network) |
| `brave_search.api_key` | Brave Search API key |
| `fred.api_key` | FRED API key |
| `finnhub.api_key` | Finnhub API key |
| `schedule.briefing_days` | e.g. `["monday", "thursday"]` |
| `schedule.briefing_time` | e.g. `"07:00"` |
| `user.language` | `"de"` or `"en"` |
| `web.port` | Dashboard port (default: 8080) |

## Deployment

Designed for always-on low-power devices like a Raspberry Pi (~90MB RAM), but any Linux box with systemd works.

```bash
# On the server
git clone https://github.com/Kingler16/velora.git ~/velora && cd ~/velora
python3 setup.py                 # configure (channels, keys, portfolio)
bash scripts/setup_server.sh     # services + cron
```

`setup_server.sh` sets up the web dashboard service, the Telegram bot service (only if Telegram is configured), a daily check that the Claude login still works, and cron jobs for briefings (schedule from `settings.json`) and the monthly report. Re-run it after changing channels.

Log Claude in once with a long-lived token: `claude setup-token`, then `./venv/bin/python scripts/set_oauth_token.py`.

Updates: `git pull`, then `sudo systemctl restart velora-web velora-bot`.

For access on the go, a VPN like [Tailscale](https://tailscale.com) is the simplest option — the iOS app switches between home Wi-Fi and Tailscale automatically.

## API Costs

| Service | Cost | Notes |
|---------|------|-------|
| Claude Code CLI | Included in Max ($100/mo) or Pro ($20/mo) | No separate API costs |
| yfinance | Free | No API key needed |
| Brave Search | Free tier: 2,000/month | Sufficient for 2 briefings/week |
| FRED / ECB | Free | US + EU macro data |
| Finnhub | Free tier: 60 calls/min | Sentiment + news |

## Disclaimer

For **educational and informational purposes only**. Not financial advice. AI analysis may contain errors. Always do your own research. No liability for financial losses.

## License

MIT
