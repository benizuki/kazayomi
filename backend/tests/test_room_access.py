"""Ayame の認証 Webhook。ルームIDを知っているだけでは入れないこと。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.auth import require_principal
from domain import devices, room_access, servers, turn
from domain.common import NotFoundError
from main import app
from tests.conftest import make_room, make_group, principal
from tests.test_devices import FakeKazami


def _register(room: str, key: str | None) -> dict:
    payload = {"roomId": room, "clientId": "c", "connectionId": "x"}
    if key is not None:
        payload["signalingKey"] = key
    return room_access.authenticate(payload)


def test_viewer_ticket_is_for_one_room_and_single_use():
    room = make_room("A", "room-a")
    make_room("B", "room-b")
    ticket = room_access.issue_room_ticket(room["id"], principal())["ticket"]
    assert _register("room-b", ticket)["allowed"] is False  # 別のルームには使えない（そのまま使い切る）
    ticket = room_access.issue_room_ticket(room["id"], principal())["ticket"]
    assert _register("room-a", ticket)["allowed"] is True
    assert _register("room-a", ticket)["allowed"] is False


def test_ticket_requires_visible_room():
    make_group("a")
    room = make_room("A", "room-a", "a")
    with pytest.raises(NotFoundError):
        room_access.issue_room_ticket(room["id"], principal("user", {"other"}))


def test_device_token_only_opens_its_own_room():
    mine = make_room("A", "room-a")
    make_room("B", "room-b")
    device = devices.create_device({"name": "端末", "room_id": mine["id"]})
    kazami = FakeKazami()
    devices.enroll(kazami.enroll_payload(devices.issue_enrollment(device["id"])["token"]))
    token = kazami.login()["access_token"]
    assert _register("room-a", token)["allowed"] is True
    assert _register("room-a", token)["allowed"] is True  # 端末は再接続を繰り返すので何度でも
    assert _register("room-b", token)["allowed"] is False
    devices.clear_enrollment(device["id"])
    assert _register("room-a", token)["allowed"] is False


def test_unknown_or_missing_key_is_denied():
    make_room("A", "room-a")
    assert _register("room-a", None) == {"allowed": False, "reason": "signalingKey is required"}
    assert _register("room-a", "guess")["allowed"] is False


@pytest.fixture
def client(isolated_storage):
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_webhook_always_answers_200_with_allowed(client: TestClient, monkeypatch):
    from config.settings import get_settings

    room = make_room("A", "room-a")
    app.dependency_overrides[require_principal] = lambda: principal()
    ticket = client.post(f"/api/rooms/{room['id']}/ticket").json()["ticket"]
    app.dependency_overrides.clear()

    # TestClient の接続元は "testclient"（IP ではない）なので、許可リストを広げて試す
    monkeypatch.setattr(get_settings(), "ayame_webhook_allowed_ips", ("0.0.0.0/0", "::/0"))
    monkeypatch.setattr(get_settings(), "ayame_webhook_secret", "s3cret")
    monkeypatch.setattr("api.ayame_api._from_ayame", lambda _r: True)
    wrong = client.post("/api/ayame/authn?key=nope", json={"roomId": "room-a", "signalingKey": ticket})
    assert wrong.status_code == 200 and wrong.json()["allowed"] is False
    ok = client.post("/api/ayame/authn?key=s3cret", json={"roomId": "room-a", "signalingKey": ticket})
    assert ok.status_code == 200 and ok.json()["allowed"] is True


def test_webhook_only_answers_ayame(client: TestClient):
    # 既定では 127.0.0.1 からだけ。TestClient（接続元 "testclient"）は外からとみなして断る
    res = client.post("/api/ayame/authn", json={"roomId": "room-a", "signalingKey": "x"})
    assert res.status_code == 403


class _Req:
    def __init__(self, host: str, headers: dict | None = None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def test_from_ayame_checks_source_ip_and_proxy_headers():
    from api.ayame_api import _from_ayame

    assert _from_ayame(_Req("127.0.0.1")) is True
    assert _from_ayame(_Req("::1")) is True
    assert _from_ayame(_Req("192.168.1.20")) is False
    # 同じホストのリバースプロキシを通った外からのリクエストは、127.0.0.1 に見えても断る
    assert _from_ayame(_Req("127.0.0.1", {"x-forwarded-for": "203.0.113.5"})) is False
    assert _from_ayame(_Req("127.0.0.1", {"forwarded": "for=203.0.113.5"})) is False


# ── Cloudflare TURN ─────────────────────────────

class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._body


def _cloudflare_server(**extra) -> dict:
    return servers.create_server({
        "name": "CF", "signaling_url": "wss://ayame.example.com/signaling", "kind": "cloudflare",
        "turn_key_id": "key-1", "turn_api_token": "secret-token", "is_default": True, **extra,
    })


def test_cloudflare_server_returns_turn_ice_servers_without_port_53(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers["Authorization"], json["ttl"]))
        return _FakeResponse({"iceServers": [
            {"urls": ["stun:stun.cloudflare.com:3478", "stun:stun.cloudflare.com:53"]},
            {"urls": ["turn:turn.cloudflare.com:3478?transport=udp", "turn:turn.cloudflare.com:53?transport=udp",
                      "turns:turn.cloudflare.com:443?transport=tcp"],
             "username": "u", "credential": "c"},
        ]})

    monkeypatch.setattr(turn.requests, "post", fake_post)
    _cloudflare_server()
    room = make_room("A", "room-a")
    for _ in range(2):
        ticket = room_access.issue_room_ticket(room["id"], principal())["ticket"]
        result = _register("room-a", ticket)
        assert result["allowed"] is True
        assert result["iceServers"] == [
            {"urls": ["stun:stun.cloudflare.com:3478"]},
            {"urls": ["turn:turn.cloudflare.com:3478?transport=udp", "turns:turn.cloudflare.com:443?transport=tcp"],
             "username": "u", "credential": "c"},
        ]
    # 2 回目は覚えておいた認証情報を使う
    assert calls == [(turn.API_URL.format(key_id="key-1"), "Bearer secret-token", turn.CREDENTIAL_TTL_SECONDS)]


def test_cloudflare_failure_falls_back_to_stun(monkeypatch):
    def fake_post(*args, **kwargs):
        raise turn.requests.ConnectionError("down")

    monkeypatch.setattr(turn.requests, "post", fake_post)
    _cloudflare_server()
    room = make_room("A", "room-a")
    ticket = room_access.issue_room_ticket(room["id"], principal())["ticket"]
    result = _register("room-a", ticket)
    assert result["allowed"] is True
    assert result["iceServers"] == turn.FALLBACK_ICE_SERVERS


def test_ayame_server_and_denied_register_have_no_ice_servers(monkeypatch):
    monkeypatch.setattr(turn.requests, "post", lambda *a, **k: pytest.fail("should not call cloudflare"))
    servers.create_server({"name": "A", "signaling_url": "wss://ayame.example.com/signaling", "is_default": True})
    room = make_room("A", "room-a")
    ticket = room_access.issue_room_ticket(room["id"], principal())["ticket"]
    assert "iceServers" not in _register("room-a", ticket)
    assert "iceServers" not in _register("room-a", "v1.unknown")


def test_cloudflare_server_hides_token_and_keeps_it_when_blank():
    server = _cloudflare_server()
    assert "turn_api_token" not in server and server["turn_api_token_set"] is True
    server = servers.update_server(server["id"], {**server, "turn_api_token": ""})
    assert servers.ice_server_config("anything")["api_token"] == "secret-token"
    with pytest.raises(ValueError):
        servers.create_server({"name": "x", "signaling_url": "ws://x/signaling", "kind": "cloudflare", "turn_key_id": "k"})
    # ayame に戻すと TURN の設定は消える
    servers.update_server(server["id"], {**server, "kind": "ayame"})
    assert servers.ice_server_config("anything") is None
    assert servers.get_server(server["id"])["turn_api_token_set"] is False
