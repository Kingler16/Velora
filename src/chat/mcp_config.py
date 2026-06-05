"""Generiert die MCP-Config zur Laufzeit mit absoluten Pfaden (portabel zwischen Mac und RockPi)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
_CACHE_PATH: Path | None = None


def get_mcp_config_path() -> str:
    """Schreibt die MCP-Config in einen temporären Pfad und gibt ihn zurück.

    Die Config nutzt den sys.executable aus dem aktuellen venv, sodass die
    Python-Imports für den MCP-Server-Subprocess garantiert funktionieren.
    """
    global _CACHE_PATH
    if _CACHE_PATH and _CACHE_PATH.exists():
        return str(_CACHE_PATH)

    config = {
        "mcpServers": {
            "velora": {
                "command": sys.executable,
                "args": [
                    "-m", "src.chat.mcp_server",
                ],
                "env": {
                    "PYTHONPATH": str(_BASE),
                    "VELORA_BASE": str(_BASE),
                },
                "cwd": str(_BASE),
            }
        }
    }

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix="-velora-mcp.json", delete=False, encoding="utf-8"
    )
    json.dump(config, tmp, indent=2)
    tmp.close()
    _CACHE_PATH = Path(tmp.name)
    return str(_CACHE_PATH)


VELORA_TOOLS = [
    # Read-only
    "mcp__velora__get_portfolio",
    "mcp__velora__get_position_detail",
    "mcp__velora__get_live_quote",
    "mcp__velora__get_macro_data",
    "mcp__velora__get_indices",
    "mcp__velora__get_calendar",
    "mcp__velora__fetch_news",
    "mcp__velora__get_briefings",
    "mcp__velora__get_briefing_full",
    "mcp__velora__get_recommendations",
    "mcp__velora__get_watchlist",
    "mcp__velora__search_memory",
    "mcp__velora__pin_memory",
    "mcp__velora__get_strategy_drift",
    # Write (legen pending_actions an, brauchen User-Bestätigung)
    "mcp__velora__log_trade",
    "mcp__velora__update_watchlist",
    "mcp__velora__close_recommendation",
    "mcp__velora__propose_mandate",
]

# Tools die Write-Confirmation erfordern
CONFIRMATION_REQUIRED_TOOLS = {
    "mcp__velora__log_trade",
    "mcp__velora__update_watchlist",
    "mcp__velora__close_recommendation",
    "mcp__velora__propose_mandate",
}
