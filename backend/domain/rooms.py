"""ルーム（Ayame の room）。Kazami 1 台ぶんの映像の入口。

ルームは必ずどれか 1 つのグループに属し、そのグループのユーザーにだけ見える。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from core.db import connect
from domain import groups
from domain.access import Principal
from domain.common import NotFoundError, new_id, now_local, optional_text, require_text, to_iso

# Ayame のルームIDに使える文字。URL のクエリにもそのまま載せられる範囲に限る。
_ROOM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-@:]{1,255}$")

_SELECT = """
SELECT c.*, g.name AS group_name, s.name AS server_name, s.signaling_url AS server_signaling_url
FROM rooms c
JOIN groups g ON g.id = c.group_id
LEFT JOIN servers s ON s.id = COALESCE(c.server_id, (SELECT d.id FROM servers d WHERE d.is_default = 1))
"""


def default_signaling_url() -> str:
    """サーバを選んでいないときの URL（既定のサーバ）。既定のサーバがなければ空。"""
    with connect() as conn:
        row = conn.execute("SELECT signaling_url FROM servers WHERE is_default = 1").fetchone()
    return row[0] if row else ""


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "ayame_room_id": row["ayame_room_id"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        # server_id が None なら「既定のサーバ」を使う。server_name はそのとき実際に使うサーバの名前
        "server_id": row["server_id"],
        "server_name": row["server_name"] or "",
        # シグナリング URL は、ルームのサーバ → 既定のサーバ の順で決める。どちらもなければ空（つなげない）
        "signaling_url": row["server_signaling_url"] or "",
        "note": row["note"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    ayame_room_id = require_text(payload.get("ayame_room_id"), "ルームID", max_length=255)
    if not _ROOM_ID_PATTERN.match(ayame_room_id):
        raise ValueError("ルームIDに使えるのは半角英数字と _ . - @ : だけです。Kazami の設定と同じ値を入れてください。")
    group_id = require_text(payload.get("group_id"), "グループ", max_length=64)
    if not groups.exists(group_id):
        raise ValueError("グループが見つかりません。")
    server_id = str(payload.get("server_id") or "") or None
    if server_id:
        with connect() as conn:
            if conn.execute("SELECT 1 FROM servers WHERE id = ?", (server_id,)).fetchone() is None:
                raise ValueError("サーバが見つかりません。")
    return {
        "name": require_text(payload.get("name"), "ルーム名", max_length=100),
        "ayame_room_id": ayame_room_id,
        "group_id": group_id,
        "server_id": server_id,
        "note": optional_text(payload.get("note"), "メモ"),
    }


def _unique_error(exc: sqlite3.IntegrityError) -> ValueError:
    message = str(exc)
    if "rooms.name" in message:
        return ValueError("同じ名前のルームがあります。別の名前にしてください。")
    if "rooms.ayame_room_id" in message:
        return ValueError("同じルームIDのルームがあります。1 つのルームには 1 台しか登録できません。")
    return ValueError("登録できませんでした。入力内容を確認してください。")


def list_rooms(viewer: Principal | None = None) -> list[dict[str, Any]]:
    """viewer を渡すと、その人が見られるグループのものだけを返す。"""
    with connect() as conn:
        group_ids = viewer.visible_group_ids() if viewer else None
        if group_ids is None:
            rows = conn.execute(_SELECT + " ORDER BY c.sort_order, c.name").fetchall()
        elif not group_ids:
            rows = []
        else:
            marks = ",".join("?" for _ in group_ids)
            rows = conn.execute(_SELECT + f" WHERE c.group_id IN ({marks}) ORDER BY c.sort_order, c.name", group_ids).fetchall()
    return [_record(row) for row in rows]


def get_room(room_id: str, viewer: Principal | None = None) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE c.id = ?", (room_id,)).fetchone()
    # 見られないグループのものは「無い」と答える（存在を伏せる）
    if row is None or (viewer is not None and not viewer.can_see_group(row["group_id"])):
        raise NotFoundError("ルームが見つかりません。一覧を開き直してください。")
    return _record(row)


def find_by_room(ayame_room_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE c.ayame_room_id = ?", (ayame_room_id,)).fetchone()
    return _record(row) if row else None


def create_room(payload: dict[str, Any]) -> dict[str, Any]:
    values = _validate(payload)
    now = to_iso(now_local())
    room_id = new_id()
    try:
        with connect() as conn:
            (max_order,) = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM rooms").fetchone()
            conn.execute(
                "INSERT INTO rooms (id, name, ayame_room_id, group_id, server_id, note, sort_order, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (room_id, values["name"], values["ayame_room_id"], values["group_id"], values["server_id"],
                 values["note"], max_order + 1, now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise _unique_error(exc) from exc
    return get_room(room_id)


def update_room(room_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """グループを変えても、撮像済みの画像のグループはそのまま（撮った時点のグループで残す）。"""
    get_room(room_id)
    values = _validate(payload)
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE rooms SET name = ?, ayame_room_id = ?, group_id = ?, server_id = ?, note = ?, updated_at = ? WHERE id = ?",
                (values["name"], values["ayame_room_id"], values["group_id"], values["server_id"], values["note"],
                 to_iso(now_local()), room_id),
            )
    except sqlite3.IntegrityError as exc:
        raise _unique_error(exc) from exc
    return get_room(room_id)


def delete_room(room_id: str) -> None:
    """ルームを消しても画像は残す。画像には撮像時点のルーム名を控えてある。"""
    get_room(room_id)
    with connect() as conn:
        conn.execute("UPDATE images SET room_id = NULL WHERE room_id = ?", (room_id,))
        conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
