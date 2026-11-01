"""ローカル（APP_ENV=local）で初めて起動したときに、すぐ試せるようサーバ・ルーム・デバイスを 1 つずつ作る。

作るのは 1 回だけ。作ったことを app_settings に残すので、画面で消したものを再起動で作り直さない。
サーバかルームがすでにあるとき（既存の DB をローカルで開いたときなど）も作らない。
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from core.db import connect
from domain import app_settings, devices, rooms, servers

logger = logging.getLogger(__name__)

SEEDED = "dev_seeded"
DEFAULT_GROUP_ID = "default"
SERVER_NAME = "ローカルの Ayame"
ROOM_NAME = "ローカルのルーム"
AYAME_ROOM_ID = "local"
DEVICE_NAME = "ローカルの Kazami"


def signaling_url(public_base_url: str) -> str:
    """Kazami と kazayomi の両方から届く Ayame の URL。

    DEV_SIGNALING_URL があればそれ。無ければ PUBLIC_BASE_URL のホストの 3000 番（compose の Ayame）。
    どちらも無ければ 127.0.0.1 にする。画面からは見られるが、Kazami（iPhone）からは届かない。
    """
    configured = os.getenv("DEV_SIGNALING_URL", "").strip()
    if configured:
        return configured
    host = urlsplit(public_base_url).hostname if public_base_url else None
    return f"ws://{host or '127.0.0.1'}:3000/signaling"


def _has_servers_or_rooms() -> bool:
    with connect() as conn:
        return conn.execute("SELECT EXISTS (SELECT 1 FROM servers) OR EXISTS (SELECT 1 FROM rooms)").fetchone()[0] == 1


def seed(public_base_url: str) -> bool:
    """作ったら True。"""
    if app_settings.flag(SEEDED) or _has_servers_or_rooms():
        return False
    url = signaling_url(public_base_url)
    server = servers.create_server({"name": SERVER_NAME, "signaling_url": url, "is_default": True,
                                    "note": "ローカルで初めて起動したときに作ったもの"})
    room = rooms.create_room({"name": ROOM_NAME, "ayame_room_id": AYAME_ROOM_ID, "group_id": DEFAULT_GROUP_ID})
    devices.create_device({"name": DEVICE_NAME, "room_id": room["id"]})
    app_settings.set_flag(SEEDED)
    logger.warning("dev seed: created server %s (%s), room %s, device %s", server["name"], url, room["name"], DEVICE_NAME)
    if urlsplit(url).hostname in ("127.0.0.1", "localhost"):
        logger.warning("dev seed: Kazami から %s には届きません。DEV_SIGNALING_URL か マスター › サーバ で PC の IP にしてください", url)
    return True
