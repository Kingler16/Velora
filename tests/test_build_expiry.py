"""Tests für die Warnung vor dem Ablauf des TestFlight-Builds."""

from datetime import date

import pytest

from src.delivery import build_expiry as be


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(be, "STATE_PATH", tmp_path / "build_expiry.json")


DEV = [{"environment": "production", "app_version": "1.0 (20261029.1625)"}]


def test_build_date_from_testflight_number():
    assert be.build_date("1.0 (20261029.1625)") == date(2026, 10, 29)
    assert be.build_date("1.0 (1)") is None
    assert be.build_date(None) is None


def test_sandbox_and_unknown_builds_are_skipped():
    devices = [{"environment": "sandbox", "app_version": "1.0 (20261029.1625)"},
               {"environment": "production", "app_version": "1.0 (7)"}]
    assert be.expiry_status(devices, date(2027, 1, 20)) is None


def test_status_uses_oldest_build():
    devices = DEV + [{"environment": "production", "app_version": "1.0 (20261201.0900)"}]
    s = be.expiry_status(devices, date(2027, 1, 20))
    assert s["expires"] == "2027-01-27" and s["days_left"] == 7


def test_reminder_once_per_threshold():
    sent = []
    send = lambda **kw: sent.append(kw)
    assert not be.check_and_notify(DEV, date(2027, 1, 1), send)          # 26 Tage: noch nichts
    assert be.check_and_notify(DEV, date(2027, 1, 13), send)              # 14 Tage
    assert not be.check_and_notify(DEV, date(2027, 1, 14), send)          # gleiche Schwelle
    assert be.check_and_notify(DEV, date(2027, 1, 20), send)              # 7 Tage
    assert "in 7 Tagen" in sent[-1]["title"]
    assert sent[-1]["category"] == "system_error"


def test_no_burst_after_downtime_and_none_after_expiry():
    sent = []
    send = lambda **kw: sent.append(kw)
    assert be.check_and_notify(DEV, date(2027, 1, 26), send)              # 1 Tag, erste Prüfung
    assert not be.check_and_notify(DEV, date(2027, 1, 26), send)
    assert len(sent) == 1
    assert not be.check_and_notify(DEV, date(2027, 2, 1), send)           # abgelaufen
