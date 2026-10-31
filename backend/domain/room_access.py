"""Ayame のルームに入ってよいかを決める（認証 Webhook）。

Ayame は register を受けるたびに kazayomi の Webhook を呼ぶ。ルームに入れるのは次の 2 つだけ:
- Kazami: signalingKey がデバイスのアクセストークンで、そのデバイスに割り当てたルームに入るとき
- ブラウザ: signalingKey が入室チケットで、チケットを発行したルームに入るとき。
  チケットは、そのルームを見られるログイン中のユーザーにだけ、接続の直前に発行する（1 分・1 回限り）

これで、ルームIDを知っているだけでは映像を見られない。
入室を許すときは、ルームのサーバが cloudflare なら TURN の iceServers も返す（Ayame が accept で両方に渡す）。
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from core.kv import get_store
from domain import devices, rooms, servers, turn
from domain.access import Principal

ROOM_TICKET_TTL_SECONDS = 60


def _key(ticket: str) -> str:
    return "room-ticket:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _issue(ayame_room_id: str, who: str) -> dict[str, Any]:
    ticket = "v1." + secrets.token_urlsafe(32)
    get_store().set(_key(ticket), json.dumps({"ayame_room_id": ayame_room_id, "email": who}), ROOM_TICKET_TTL_SECONDS)
    return {"ticket": ticket, "expires_in": ROOM_TICKET_TTL_SECONDS}


def issue_room_ticket(room_id: str, viewer: Principal) -> dict[str, Any]:
    room = rooms.get_room(room_id, viewer)  # 見られないルームなら NotFoundError
    return _issue(room["ayame_room_id"], viewer.email)


def authenticate(payload: dict[str, Any]) -> dict[str, Any]:
    """Ayame への応答。HTTP は常に 200 で返し、可否は allowed で伝える（Ayame の取り決め）。"""
    result = _decide(payload)
    if result["allowed"]:
        room = str(payload.get("roomId"))
        config = servers.ice_server_config(room)
        if config is not None:
            result["iceServers"] = turn.ice_servers(config, room)
    return result


def _decide(payload: dict[str, Any]) -> dict[str, Any]:
    ayame_room_id = str(payload.get("roomId") or "")
    key = str(payload.get("signalingKey") or "")
    if not ayame_room_id or not key:
        return {"allowed": False, "reason": "signalingKey is required"}

    # ブラウザの入室チケット。使い切りにする（再接続のたびに発行し直す）
    if key.startswith("v1."):
        raw = get_store().pop(_key(key))
        if raw is None:
            return {"allowed": False, "reason": "ticket expired"}
        ticket = json.loads(raw)
        if ticket["ayame_room_id"] != ayame_room_id:
            return {"allowed": False, "reason": "ticket is for another room"}
        return {"allowed": True, "authzMetadata": {"kind": "viewer", "email": ticket["email"]}}

    # Kazami のアクセストークン。期限内は何度でも使える（端末は再接続を繰り返すため）
    device = devices.resolve_access_token(key)
    if device is None:
        return {"allowed": False, "reason": "unknown device"}
    if device["ayame_room_id"] != ayame_room_id:
        return {"allowed": False, "reason": "device is not assigned to this room"}
    return {"allowed": True, "authzMetadata": {"kind": "device", "name": device["name"]}}
