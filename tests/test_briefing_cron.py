"""Briefing-Zeitplan → Crontab: nur der Velora-Eintrag ändert sich, nie ein zweiter Job."""

import pwd
import subprocess
from pathlib import Path

import pytest

from src import briefing_cron as bc

# Wie ihn das alte Setup-Skript angelegt hat (Pfad anonymisiert).
OLD_CRONTAB = """MAILTO=""
# Velora — Briefing Mon+Thu 7:00
0 7 * * 1,4 cd /srv/velora && ./venv/bin/python -m src.main briefing >> /srv/velora/logs/briefing.log 2>&1
# Velora — Monthly report 1st of month 9:00
0 9 1 * * cd /srv/velora && ./venv/bin/python -m src.main monthly >> /srv/velora/logs/monthly.log 2>&1
30 3 * * * /usr/local/bin/backup.sh
"""


def test_normalize_orders_days_and_accepts_string():
    assert bc.normalize("thursday, Monday", "7:05") == (["monday", "thursday"], 7, 5)
    assert bc.normalize(["sunday", "friday"], "23:59") == (["friday", "sunday"], 23, 59)


@pytest.mark.parametrize("days,time", [([], "07:00"), (["montag"], "07:00"), (["monday"], "24:00"),
                                       (["monday"], "7"), (["monday"], None)])
def test_normalize_rejects_garbage(days, time):
    with pytest.raises(bc.ScheduleError):
        bc.normalize(days, time)


def test_rewrite_replaces_only_briefing_in_place():
    block = bc.briefing_block(Path("/srv/velora"), ["tuesday", "friday"], 6, 30)
    new = bc.rewrite(OLD_CRONTAB, block)
    lines = new.splitlines()
    assert lines[0] == 'MAILTO=""'
    assert lines[1] == "# Velora — Briefing (tuesday,friday 06:30)"
    assert lines[2].startswith("30 6 * * 2,5 cd /srv/velora && ./venv/bin/python -m src.main briefing")
    assert "src.main monthly" in new and "/usr/local/bin/backup.sh" in new
    assert sum("src.main briefing" in l for l in lines) == 1
    assert "Mon+Thu" not in new
    # Erneut anwenden ändert nichts
    assert bc.rewrite(new, block) == new


def test_rewrite_never_creates_unasked():
    block = bc.briefing_block(Path("/srv/velora"), ["monday"], 7, 0)
    assert bc.rewrite("30 3 * * * /usr/local/bin/backup.sh\n", block) is None
    created = bc.rewrite("30 3 * * * /usr/local/bin/backup.sh\n", block, create=True)
    assert created.splitlines()[0] == "30 3 * * * /usr/local/bin/backup.sh"
    assert created.splitlines()[-1].startswith("0 7 * * 1 ")
    assert bc.rewrite("", block, create=True) == "\n".join(block) + "\n"


def test_commented_out_job_is_not_an_entry():
    block = bc.briefing_block(Path("/srv/velora"), ["monday"], 7, 0)
    assert bc.rewrite("# 0 7 * * 1 cd /x && python -m src.main briefing\n", block) is None


class FakeCrontab:
    """Ersetzt subprocess.run für `crontab`; merkt sich Inhalt und Aufrufe."""

    def __init__(self, text=None):
        self.text = text
        self.calls = []

    def __call__(self, cmd, input=None, **kw):
        self.calls.append(cmd)
        if cmd[-1] == "-l":
            if self.text is None:
                return subprocess.CompletedProcess(cmd, 1, "", "no crontab for user\n")
            return subprocess.CompletedProcess(cmd, 0, self.text, "")
        self.text = input
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def fake(monkeypatch):
    def install(text):
        f = FakeCrontab(text)
        monkeypatch.setattr(bc.shutil, "which", lambda name: "/usr/bin/crontab")
        monkeypatch.setattr(bc.subprocess, "run", f)
        return f
    return install


def test_apply_updates_existing_entry(fake, tmp_path):
    f = fake(OLD_CRONTAB.replace("/srv/velora", str(tmp_path)))
    result = bc.apply_briefing_schedule(["wednesday"], "08:15", install_dir=tmp_path)
    assert result["applied"] and "Mi um 08:15" in result["message"]
    assert f"15 8 * * 3 cd {tmp_path} && ./venv/bin/python -m src.main briefing" in f.text


def test_apply_unchanged_does_not_write(fake, tmp_path):
    block = bc.briefing_block(tmp_path, ["monday", "thursday"], 7, 0)
    f = fake("\n".join(block) + "\n")
    assert bc.apply_briefing_schedule(["monday", "thursday"], "07:00", install_dir=tmp_path)["applied"]
    assert all(c[-1] == "-l" for c in f.calls)


def test_apply_without_entry_leaves_crontab_alone(fake, tmp_path):
    f = fake(None)
    result = bc.apply_briefing_schedule(["monday"], "07:00", install_dir=tmp_path)
    assert not result["applied"] and "setup_server.sh" in result["message"]
    assert f.text is None


def test_apply_without_cron(monkeypatch, tmp_path):
    monkeypatch.setattr(bc.shutil, "which", lambda name: None)
    assert not bc.apply_briefing_schedule(["monday"], "07:00", install_dir=tmp_path)["applied"]


def test_root_edits_the_owners_crontab(fake, tmp_path, monkeypatch):
    """Web-Dienst als root, Velora gehört einem normalen Benutzer → dessen Crontab."""
    owner = pwd.getpwuid(tmp_path.stat().st_uid).pw_name
    if owner == "root":
        pytest.skip("Test läuft selbst als root")
    monkeypatch.setattr(bc.os, "geteuid", lambda: 0)
    f = fake(OLD_CRONTAB.replace("/srv/velora", str(tmp_path)))
    bc.apply_briefing_schedule(["friday"], "06:00", install_dir=tmp_path)
    assert f.calls and all(c[:3] == ["crontab", "-u", owner] for c in f.calls)


def test_settings_endpoint_rejects_invalid_schedule():
    from fastapi.testclient import TestClient
    from src.web.app import app

    r = TestClient(app).post("/api/settings", json={"schedule": {"briefing_days": ["montag"], "briefing_time": "07:00"}})
    assert r.status_code == 400 and "Wochentage" in r.json()["error"]
