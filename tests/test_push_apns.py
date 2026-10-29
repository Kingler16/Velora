"""APNs-Versand für die iOS-App, Geräte-Registrierung und Chat-Antworten im Hintergrund."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from src.chat import db
from src.delivery import apns


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "chat.db")
    db.init_db()
    return db


@pytest.fixture
def apns_cfg(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_bytes(pem)
    settings = {"apns": {"key_path": str(key_path), "key_id": "TESTKEY123",
                         "team_id": "TEAM123456", "bundle_id": "com.example.velora"}}
    monkeypatch.setattr(apns, "load_settings", lambda: settings)
    apns._token_cache.clear()
    return settings["apns"]


class _FakeResponse:
    def __init__(self, status, reason=""):
        self.status_code = status
        self._reason = reason
        self.text = reason

    def json(self):
        return {"reason": self._reason} if self._reason else {}


class _FakeClient:
    """Ersetzt httpx.Client: antwortet je Gerätetoken mit vorgegebenem Status."""

    calls: list = []
    answers: dict = {}

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, content, headers):
        _FakeClient.calls.append((url, json.loads(content), headers))
        token = url.rsplit("/", 1)[-1]
        return _FakeResponse(*_FakeClient.answers.get(token, (200,)))


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    _FakeClient.calls = []
    _FakeClient.answers = {}
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return _FakeClient


def test_payload_shape():
    p = apns.build_payload("briefings", "Briefing · 29.10.", "Neues Briefing", "/briefings", {"x": 1})
    assert p["aps"]["alert"] == {"title": "Briefing · 29.10.", "body": "Neues Briefing"}
    assert p["aps"]["thread-id"] == "briefings"
    assert p["url"] == "/briefings" and p["category"] == "briefings" and p["data"] == {"x": 1}


def test_payload_drops_oversized_data():
    p = apns.build_payload("x", "t", "b", "/", {"blob": "a" * 5000})
    assert "data" not in p


def test_not_configured_sends_nothing(chat_db, monkeypatch, fake_httpx):
    monkeypatch.setattr(apns, "load_settings", lambda: {})
    chat_db.upsert_apns_device("ab" * 32, "production")
    assert apns.send_apns("briefings", "t", "b") == 0
    assert fake_httpx.calls == []


def test_sends_to_right_host_and_drops_dead_tokens(chat_db, apns_cfg, fake_httpx):
    good, sandbox, dead = "aa" * 32, "bb" * 32, "cc" * 32
    chat_db.upsert_apns_device(good, "production")
    chat_db.upsert_apns_device(sandbox, "sandbox")
    chat_db.upsert_apns_device(dead, "production")
    fake_httpx.answers[dead] = (400, "BadDeviceToken")

    sent = apns.send_apns("chat_reply", "Velora", "Antwort", url="/chat?thread=1", tag="chat-1")

    assert sent == 2
    hosts = {url.split("/3/")[0] for url, _, _ in fake_httpx.calls}
    assert hosts == {apns.APNS_HOSTS["production"], apns.APNS_HOSTS["sandbox"]}
    _, payload, headers = fake_httpx.calls[0]
    assert headers["apns-topic"] == "com.example.velora"
    assert headers["apns-collapse-id"] == "chat-1"
    assert headers["authorization"].startswith("bearer ")
    assert payload["url"] == "/chat?thread=1"
    active = {d["token"] for d in chat_db.get_active_apns_devices()}
    assert active == {good, sandbox}


def test_provider_token_is_reused(apns_cfg):
    cfg = apns.apns_config()
    assert apns._provider_token(cfg) == apns._provider_token(cfg)


def test_push_category_toggle_also_stops_apns(chat_db, apns_cfg, fake_httpx):
    from src.delivery.push_sender import send_push
    chat_db.upsert_apns_device("aa" * 32, "production")
    chat_db.set_notification_preference("briefings", telegram_enabled=False, push_enabled=False)
    assert send_push("briefings", "t", "b") == 0
    chat_db.set_notification_preference("briefings", telegram_enabled=False, push_enabled=True)
    assert send_push("briefings", "t", "b") == 1


def test_new_categories_default_without_telegram(chat_db):
    prefs = chat_db.get_notification_preferences()
    assert prefs["chat_reply"] == {"telegram_enabled": False, "push_enabled": True}
    assert prefs["system_error"] == {"telegram_enabled": False, "push_enabled": True}
    assert prefs["briefings"]["telegram_enabled"] is True


# ── API ───────────────────────────────────────────────────────

@pytest.fixture
def client(chat_db):
    from src.web.app import app
    return TestClient(app)


def test_register_device(client, chat_db):
    token = "AB" * 32
    r = client.post("/api/push/apns/register", json={"token": token, "environment": "sandbox",
                                                     "device_name": "iPhone", "app_version": "1.0 (5)"})
    assert r.status_code == 200
    assert chat_db.get_active_apns_devices() == [{"token": token.lower(), "environment": "sandbox",
                                                  "device_name": "iPhone"}]
    client.post("/api/push/apns/unregister", json={"token": token})
    assert chat_db.get_active_apns_devices() == []


@pytest.mark.parametrize("body", [{"token": "xyz"}, {"token": "ab" * 32, "environment": "dev"}])
def test_register_rejects_garbage(client, body):
    assert client.post("/api/push/apns/register", json=body).status_code == 400


def test_preferences_partial_update_keeps_telegram(client, chat_db):
    chat_db.set_notification_preference("briefings", telegram_enabled=False, push_enabled=True)
    client.post("/api/push/preferences", json={"briefings": {"push_enabled": False}})
    assert chat_db.get_notification_preferences()["briefings"] == {"telegram_enabled": False,
                                                                   "push_enabled": False}


# ── System-Alarme ─────────────────────────────────────────────

@pytest.mark.parametrize("pushed,telegram_pref,expect_telegram", [
    (1, False, False),   # Push kam an → kein Telegram
    (0, False, True),    # nichts zugestellt → Telegram als Notnagel
    (1, True, True),     # ausdrücklich eingeschaltet
])
def test_system_alert_telegram_fallback(chat_db, monkeypatch, pushed, telegram_pref, expect_telegram):
    from src.delivery import alerts, push_sender, telegram

    chat_db.set_notification_preference("system_error", telegram_enabled=telegram_pref, push_enabled=True)
    monkeypatch.setattr(push_sender, "send_push_safe", lambda **kw: pushed)
    monkeypatch.setattr(alerts, "load_settings", lambda: {"telegram": {"bot_token": "t", "chat_id": "1"}})
    sent = []

    async def fake_tg(bot_token, chat_id, msg):
        sent.append(msg)

    monkeypatch.setattr(telegram, "send_error_alert", fake_tg)
    asyncio.run(alerts.send_system_alert("Briefing fehlgeschlagen", "boom"))
    assert bool(sent) is expect_telegram


# ── Chat: Antwort läuft zu Ende ───────────────────────────────

def _fake_stream(texts):
    from src.chat.claude_stream import StreamEvent

    async def gen(**kwargs):
        for t in texts:
            yield StreamEvent("text_delta", {"text": t})
        yield StreamEvent("done", {"session_id": "s1"})
    return gen


def test_chat_reply_saved_without_push_when_client_stays(client, chat_db, monkeypatch):
    from src.chat import routes
    monkeypatch.setattr(routes, "stream_chat", _fake_stream(["Hallo ", "Welt"]))
    monkeypatch.setattr(routes, "build_full_system_prompt", lambda *a: "")
    monkeypatch.setattr(routes, "build_user_message_with_history", lambda *a: "")
    pushes = []
    monkeypatch.setattr(routes, "_push_chat_reply", lambda *a: pushes.append(a))

    thread = chat_db.create_thread("Test")
    r = client.post(f"/api/chat/threads/{thread['id']}/message", json={"message": "Hi"})
    assert "Hallo " in r.text and "event: done" in r.text

    detail = client.get(f"/api/chat/threads/{thread['id']}").json()
    assert detail["running"] is False
    assert [m["content"] for m in detail["messages"] if m["role"] == "assistant"] == ["Hallo Welt"]
    assert pushes == []


def test_stop_without_running_reply(client, chat_db):
    thread = chat_db.create_thread("Test")
    assert client.post(f"/api/chat/threads/{thread['id']}/stop").json() == {"stopped": False}
