"""撮像トークンの発行と、Kazami からのアップロードの受け付け。

ブラウザが撮像を頼むたびに、撮像IDと使い捨てのトークンを発行する。
Kazami はそのトークンでアップロードする。端末に長く使える鍵を持たせずに済み、
ログインのない構成でも「頼まれていない画像」は受け付けない。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any

from core.kv import get_store
from domain import devices, images, rooms
from domain.access import Principal
from domain.common import NotFoundError, new_id, normalize_tags, now_local, optional_text, parse_datetime, to_iso

# 結果を確認できる期間。ブラウザが DataChannel の結果を受け取り損ねても、ここで追える。
_RESULT_TTL_SECONDS = 600


def _pending_key(capture_id: str) -> str:
    return f"capture:{capture_id}"


def _result_key(capture_id: str) -> str:
    return f"capture-result:{capture_id}"


def _hash(token: str) -> str:
    # トークンそのものは保存しない。置き場を覗かれても使えないようにするため。
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_capture(payload: dict[str, Any], *, viewer: Principal, ttl_seconds: int) -> dict[str, Any]:
    room_id = str(payload.get("room_id") or "")
    if not room_id:
        raise ValueError("撮像するルームを指定してください。")
    room = rooms.get_room(room_id, viewer)
    capture_id = new_id()
    token = secrets.token_urlsafe(32)
    expires_at = now_local() + timedelta(seconds=ttl_seconds)
    pending = {
        "token_hash": _hash(token),
        "room_id": room["id"],
        # 画像はルームのグループに入れる。撮像までの間にルームのグループが変わっても、頼んだ時点のグループで残す
        "group_id": room["group_id"],
        "captured_by": viewer.email,
        "tags": normalize_tags(payload.get("tags")),
        "note": optional_text(payload.get("note"), "メモ"),
        "expires_at": to_iso(expires_at),
    }
    get_store().set(_pending_key(capture_id), json.dumps(pending, ensure_ascii=False), ttl_seconds)
    return {"capture_id": capture_id, "token": token, "expires_at": to_iso(expires_at)}


def capture_status(capture_id: str) -> dict[str, Any]:
    store = get_store()
    result = store.get(_result_key(capture_id))
    if result is not None:
        return {"capture_id": capture_id, "status": "done", **json.loads(result)}
    if store.get(_pending_key(capture_id)) is not None:
        return {"capture_id": capture_id, "status": "pending"}
    return {"capture_id": capture_id, "status": "expired"}


class CaptureAuthError(PermissionError):
    """トークンが無い・違う・期限切れ。api 層で 401 にする。"""


def accept_upload(capture_id: str, token: str, data: bytes, *, captured_at: str | None, source_name: str) -> dict[str, Any]:
    store = get_store()
    raw = store.get(_pending_key(capture_id))
    if raw is None:
        raise CaptureAuthError("撮像の受付期限が切れています。もう一度撮像してください。")
    pending = json.loads(raw)
    if not token or not hmac.compare_digest(pending["token_hash"], _hash(token)):
        raise CaptureAuthError("撮像トークンが正しくありません。")
    # 照合できてから取り出す。違うトークンで叩かれても、正しい撮像を潰さないため。
    # 取り出せなかった場合は、同じトークンで同時に送られた片方が先に使ったということ。
    if store.pop(_pending_key(capture_id)) is None:
        raise CaptureAuthError("この撮像はすでに受け付けています。")

    try:
        room: dict[str, Any] | None = rooms.get_room(pending["room_id"])
    except NotFoundError:
        room = None
    record = images.save_image(
        data,
        source="camera",
        captured_at=parse_datetime(captured_at),
        room=room,
        group_id=pending["group_id"],
        captured_by=pending["captured_by"],
        source_name=source_name,
        tags=pending["tags"],
        note=pending["note"],
    )
    store.set(_result_key(capture_id), json.dumps({"image_id": record["id"]}), _RESULT_TTL_SECONDS)
    return record


def accept_device_upload(access_token: str, data: bytes, *, captured_at: str | None, source_name: str) -> dict[str, Any]:
    """Kazami の撮像ボタンで撮った画像を受け取る（kazayomi から頼まれていない撮像）。

    登録済みのデバイスのアクセストークンで確かめ、そのデバイスに割り当てたルームとグループに入れる。
    撮像した人には、デバイス名を `device:<名前>` の形で残す（ユーザーのメールアドレスと見分けるため）。
    """
    device = devices.resolve_access_token(access_token)
    if device is None:
        raise CaptureAuthError("端末の認証が切れています。接続し直してから、もう一度撮像してください。")
    if not device["room_id"]:
        raise ValueError("この端末にはルームが割り当てられていません。kazayomi のマスター › デバイス でルームを割り当ててください。")
    room = rooms.get_room(device["room_id"])
    return images.save_image(
        data,
        source="camera",
        captured_at=parse_datetime(captured_at),
        room=room,
        group_id=room["group_id"],
        captured_by=f"device:{device['name']}",
        source_name=source_name,
    )
