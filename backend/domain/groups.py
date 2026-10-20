"""グループ。ルーム・画像・アルバムの見える範囲を分ける単位。

グループごとに、画像の置き場（rustfs）の容量の上限（quota_bytes）を持てる。使用量は画像とサムネイルの大きさの合計。
rustfs のバケットは全グループで 1 つなので、rustfs の機能ではなく kazayomi が保存のときに確かめる（images.save_image）。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from core.db import connect
from domain.app_settings import parse_quota
from domain.common import NotFoundError, now_local, require_text, to_iso

_GROUP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "room_count": row["room_count"],
        "user_count": row["user_count"],
        "image_count": row["image_count"],
        "usage_bytes": row["usage_bytes"],
        "quota_bytes": row["quota_bytes"],
    }


_SELECT = """
SELECT g.*,
       (SELECT COUNT(*) FROM rooms c WHERE c.group_id = g.id) AS room_count,
       (SELECT COUNT(*) FROM user_groups ug WHERE ug.group_id = g.id) AS user_count,
       (SELECT COUNT(*) FROM images i WHERE i.group_id = g.id) AS image_count,
       (SELECT COALESCE(SUM(i.size_bytes + i.thumb_bytes), 0) FROM images i WHERE i.group_id = g.id) AS usage_bytes
FROM groups g
"""


def list_groups(group_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """group_ids を渡すとその中だけを返す（None なら全部）。"""
    with connect() as conn:
        if group_ids is None:
            rows = conn.execute(_SELECT + " ORDER BY g.name").fetchall()
        elif not group_ids:
            rows = []
        else:
            marks = ",".join("?" for _ in group_ids)
            rows = conn.execute(_SELECT + f" WHERE g.id IN ({marks}) ORDER BY g.name", group_ids).fetchall()
    return [_record(row) for row in rows]


def get_group(group_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE g.id = ?", (group_id,)).fetchone()
    if row is None:
        raise NotFoundError("グループが見つかりません。")
    return _record(row)


def create_group(payload: dict[str, Any]) -> dict[str, Any]:
    group_id = require_text(payload.get("id"), "グループID", max_length=64)
    if not _GROUP_ID_PATTERN.match(group_id):
        raise ValueError("グループIDに使えるのは半角英数字と _ - だけです。")
    name = require_text(payload.get("name"), "グループ名", max_length=100)
    quota = parse_quota(payload.get("quota_bytes"))
    now = to_iso(now_local())
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO groups (id, name, quota_bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (group_id, name, quota, now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じグループIDかグループ名がすでにあります。") from exc
    return get_group(group_id)


def update_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """グループIDは変えられない（画像やアルバムが参照しているため）。名前と容量の上限を変える。

    quota_bytes を送らなければ上限はそのまま。空（None）を送ると無制限にする。
    """
    current = get_group(group_id)
    name = require_text(payload.get("name"), "グループ名", max_length=100)
    quota = parse_quota(payload["quota_bytes"]) if "quota_bytes" in payload else current["quota_bytes"]
    try:
        with connect() as conn:
            conn.execute("UPDATE groups SET name = ?, quota_bytes = ?, updated_at = ? WHERE id = ?",
                         (name, quota, to_iso(now_local()), group_id))
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のグループがあります。") from exc
    return get_group(group_id)


def delete_group(group_id: str) -> None:
    """使われているグループは消さない。消すと画像やアルバムが誰からも見えなくなるため。"""
    get_group(group_id)
    with connect() as conn:
        used = {
            "ルーム": conn.execute("SELECT COUNT(*) FROM rooms WHERE group_id = ?", (group_id,)).fetchone()[0],
            "画像": conn.execute("SELECT COUNT(*) FROM images WHERE group_id = ?", (group_id,)).fetchone()[0],
            "アルバム": conn.execute("SELECT COUNT(*) FROM albums WHERE group_id = ?", (group_id,)).fetchone()[0],
        }
        in_use = [f"{label} {count} 件" for label, count in used.items() if count]
        if in_use:
            raise ValueError(f"このグループには{'・'.join(in_use)}があるため削除できません。先に移すか削除してください。")
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))


def exists(group_id: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone() is not None
