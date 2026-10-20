"""Ayame の認証 Webhook。ルームIDを知っているだけでは入れないこと。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.auth import require_principal
from domain import devices, room_access
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
