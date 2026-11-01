"""ローカルで初めて起動したときの初期データ。"""
from __future__ import annotations

from domain import dev_seed, devices, rooms, servers


def test_seed_creates_server_room_and_device():
    assert dev_seed.seed("http://192.168.1.10:8080") is True

    server = servers.default_server()
    assert server is not None and server["signaling_url"] == "ws://192.168.1.10:3000/signaling"
    [room] = rooms.list_rooms()
    assert room["ayame_room_id"] == "local" and room["group_id"] == "default"
    assert room["signaling_url"] == server["signaling_url"]
    [device] = devices.list_devices()
    assert device["room_id"] == room["id"]


def test_seed_runs_only_once_even_after_deleting():
    assert dev_seed.seed("") is True
    # 画面で消しても、再起動で作り直さない
    for d in devices.list_devices():
        devices.delete_device(d["id"])
    for r in rooms.list_rooms():
        rooms.delete_room(r["id"])
    for s in servers.list_servers():
        servers.delete_server(s["id"])
    assert dev_seed.seed("") is False
    assert servers.list_servers() == []


def test_seed_skips_when_servers_exist():
    servers.create_server({"name": "既存", "signaling_url": "ws://ayame.example:3000/signaling", "is_default": True})
    assert dev_seed.seed("") is False
    assert [s["name"] for s in servers.list_servers()] == ["既存"]


def test_signaling_url_fallbacks():
    assert dev_seed.signaling_url("https://kazayomi.example:8443") == "ws://kazayomi.example:3000/signaling"
    assert dev_seed.signaling_url("") == "ws://127.0.0.1:3000/signaling"
