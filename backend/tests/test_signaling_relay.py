"""ブラウザ用のシグナリング中継。偽の Ayame（受け取ったものを返す）を立てて確かめる。"""
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve

import api.signaling_api as signaling_api
from domain import servers
from main import app
from tests.conftest import make_room, make_group, principal


@pytest.fixture
def fake_ayame():
    """受け取ったメッセージに "echo:" を付けて返す WebSocket サーバー。"""
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: dict = {}

    async def handler(ws):
        async for message in ws:
            await ws.send("echo:" + message)

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            state["port"] = server.sockets[0].getsockname()[1]
            state["stop"] = loop.create_future()
            ready.set()
            await state["stop"]

    thread = threading.Thread(target=loop.run_until_complete, args=(main(),), daemon=True)
    thread.start()
    ready.wait(5)
    yield f"ws://127.0.0.1:{state['port']}/signaling"
    loop.call_soon_threadsafe(state["stop"].set_result, None)
    thread.join(5)


@pytest.fixture
def client(isolated_storage):
    return TestClient(app)


def test_relays_messages_both_ways(client, fake_ayame, monkeypatch):
    server = servers.create_server({"name": "fake", "signaling_url": fake_ayame})
    from domain import rooms
    room = rooms.create_room({"name": "A", "ayame_room_id": "room-a", "group_id": "default", "server_id": server["id"]})
    monkeypatch.setattr(signaling_api, "current_principal", lambda _ws: principal())
    with client.websocket_connect(f"/api/rooms/{room['id']}/signaling", headers={"origin": "http://testserver"}) as ws:
        ws.send_text('{"type":"register"}')
        assert ws.receive_text() == 'echo:{"type":"register"}'


def _close_code(client, path: str, origin: str = "http://testserver") -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect(path, headers={"origin": origin}) as ws:
            ws.receive_text()
    return info.value.code


def test_requires_login_and_same_origin(client, monkeypatch):
    room = make_room("A", "room-a")
    path = f"/api/rooms/{room['id']}/signaling"
    assert _close_code(client, path) == 4401
    monkeypatch.setattr(signaling_api, "current_principal", lambda _ws: principal())
    assert _close_code(client, path, origin="https://evil.example.com") == 4403


def test_hides_rooms_of_other_groups(client, monkeypatch):
    make_group("b")
    room = make_room("B", "room-b", "b")
    monkeypatch.setattr(signaling_api, "current_principal", lambda _ws: principal("user", {"default"}))
    assert _close_code(client, f"/api/rooms/{room['id']}/signaling") == 4404


def test_reports_unreachable_ayame(client, monkeypatch):
    from domain import rooms
    server = servers.create_server({"name": "down", "signaling_url": "ws://127.0.0.1:9/signaling"})
    room = rooms.create_room({"name": "A", "ayame_room_id": "room-a", "group_id": "default", "server_id": server["id"]})
    monkeypatch.setattr(signaling_api, "current_principal", lambda _ws: principal())
    assert _close_code(client, f"/api/rooms/{room['id']}/signaling") == 4502
