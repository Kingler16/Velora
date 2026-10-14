"""Trade-Buchung: Depot-genauer Verkauf (ausgelöste Stops) und Ausführungsdatum."""

import json

import pytest

from src.analysis import memory
from src.delivery import portfolio_io
from src.delivery.telegram import update_portfolio_position
from src.data.holdings import _position_value_eur


@pytest.fixture
def portfolio_file(tmp_path, monkeypatch):
    path = tmp_path / "portfolio.json"
    monkeypatch.setattr(portfolio_io, "PORTFOLIO_PATH", path)
    monkeypatch.setattr(portfolio_io, "LOCK_FILE", tmp_path / ".portfolio.lock")
    monkeypatch.setattr(portfolio_io, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    path.write_text(json.dumps({
        "accounts": {
            "trade_republic": {"positions": [
                {"ticker": "AMZN", "name": "Amazon", "shares": 3.0, "buy_in": 200.0, "buy_in_eur": 200.0, "currency": "EUR"},
            ]},
            "erste_bank": {"positions": [
                {"ticker": "AMZN", "name": "Amazon", "shares": 4.0, "buy_in": 180.0, "buy_in_eur": 180.0, "currency": "EUR",
                 "stop_loss": 210.0, "stop_currency": "USD"},
            ]},
        },
        "bank_accounts": {},
    }))
    return path


def _positions(path, account):
    return json.loads(path.read_text())["accounts"][account]["positions"]


def test_sell_hits_requested_account(portfolio_file):
    assert update_portfolio_position("sell", "AMZN", 4.0, 190.0, account="erste_bank")
    assert _positions(portfolio_file, "erste_bank") == []
    assert _positions(portfolio_file, "trade_republic")[0]["shares"] == 3.0


def test_sell_without_account_keeps_old_behaviour(portfolio_file):
    assert update_portfolio_position("sell", "AMZN", 1.0, 190.0)
    assert _positions(portfolio_file, "trade_republic")[0]["shares"] == 2.0
    assert _positions(portfolio_file, "erste_bank")[0]["shares"] == 4.0


def test_trade_date_lands_in_history(portfolio_file, tmp_path):
    update_portfolio_position("sell", "AMZN", 4.0, 190.0, account="erste_bank", trade_date="2026-10-13")
    history = json.loads((tmp_path / "trade_history.json").read_text())
    assert history[-1]["date"] == "2026-10-13"
    assert history[-1]["account"] == "erste_bank"


def test_buy_marks_buy_in_as_eur(portfolio_file):
    data = json.loads(portfolio_file.read_text())
    data["accounts"]["trade_republic"]["positions"][0]["currency"] = "USD"
    portfolio_file.write_text(json.dumps(data))
    update_portfolio_position("buy", "AMZN", 1.0, 220.0, account="trade_republic")
    pos = _positions(portfolio_file, "trade_republic")[0]
    assert pos["currency"] == "EUR"
    assert pos["buy_in"] == pos["buy_in_eur"] == 205.0


def test_lookthrough_value_uses_quote_currency():
    # Buy-in in EUR erfasst, Kurs notiert aber in USD → muss umgerechnet werden.
    pos = {"ticker": "MSFT", "shares": 2, "currency": "EUR", "buy_in_eur": 300.0}
    md = {"positions": {"MSFT": {"price": {"current_price": 480.0, "currency": "USD"}}}}
    assert _position_value_eur(pos, md, 1.2) == pytest.approx(800.0)
