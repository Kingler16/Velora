"""Offene Orders: optionales Gültig-bis-Datum."""

import pytest

from src.analysis import orders


@pytest.fixture(autouse=True)
def tmp_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(orders, "ORDERS_PATH", tmp_path / "orders.json")
    monkeypatch.setattr(orders, "RECS_PATH", tmp_path / "recommendations.json")


def test_valid_until_is_stored():
    r = orders.place_order("8PSG.DE", "buy", 2, 353, "erste_bank", valid_until="2026-10-30")
    assert r["ok"]
    assert orders.get_open_orders()[0]["valid_until"] == "2026-10-30"


def test_valid_until_optional_and_validated():
    assert orders.place_order("X", "buy", 1, 10, "a")["order"]["valid_until"] is None
    bad = orders.place_order("X", "buy", 1, 10, "a", valid_until="30.10.2026")
    assert not bad["ok"]
