"""アルバム（気に入った画像を集めたデータセット）。

画像は複製せず参照だけを持つ。分けたいときは画像のタグで絞り込む（ライブラリと同じ）。
"""
from __future__ import annotations

import sqlite3
from typing import Any, BinaryIO

from core.db import connect
from domain import groups, images
from domain.access import Principal
from domain.common import NotFoundError, new_id, now_local, optional_text, require_text, to_iso


def _album_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "item_count": row["item_count"],
        "cover_image_id": row["cover_image_id"],
    }


_ALBUM_SELECT = """
SELECT a.*,
       (SELECT COUNT(*) FROM album_items x WHERE x.album_id = a.id) AS item_count,
       (SELECT x.image_id FROM album_items x WHERE x.album_id = a.id ORDER BY x.added_at DESC LIMIT 1) AS cover_image_id,
       g.name AS group_name
FROM albums a
JOIN groups g ON g.id = a.group_id
"""


def _touch(conn: sqlite3.Connection, album_id: str) -> None:
    conn.execute("UPDATE albums SET updated_at = ? WHERE id = ?", (to_iso(now_local()), album_id))


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": require_text(payload.get("name"), "アルバム名", max_length=100),
        "description": optional_text(payload.get("description"), "説明"),
    }


# viewer を渡すと、その人が見られるグループのアルバムだけを扱う。見られないものは「無い」と答える。


def list_albums(viewer: Principal | None = None) -> list[dict[str, Any]]:
    group_ids = viewer.visible_group_ids() if viewer else None
    with connect() as conn:
        if group_ids is None:
            rows = conn.execute(_ALBUM_SELECT + " ORDER BY a.updated_at DESC").fetchall()
        elif not group_ids:
            rows = []
        else:
            marks = ",".join("?" for _ in group_ids)
            rows = conn.execute(_ALBUM_SELECT + f" WHERE a.group_id IN ({marks}) ORDER BY a.updated_at DESC", group_ids).fetchall()
    return [_album_record(row) for row in rows]


def get_album(album_id: str, viewer: Principal | None = None) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_ALBUM_SELECT + " WHERE a.id = ?", (album_id,)).fetchone()
    if row is None or (viewer is not None and not viewer.can_see_group(row["group_id"])):
        raise NotFoundError("アルバムが見つかりません。削除された可能性があります。")
    return _album_record(row)


def create_album(payload: dict[str, Any], viewer: Principal | None = None) -> dict[str, Any]:
    """アルバムはどれか 1 つのグループに属し、そのグループの画像だけを入れられる。"""
    values = _validate(payload)
    group_id = str(payload.get("group_id") or "")
    if not group_id and viewer is not None and viewer.group_ids is not None and len(viewer.group_ids) == 1:
        group_id = next(iter(viewer.group_ids))  # 所属が 1 つなら選ばせない
    if not group_id:
        raise ValueError("アルバムのグループを選んでください。")
    if not groups.exists(group_id):
        raise ValueError("グループが見つかりません。")
    if viewer is not None:
        viewer.require_group(group_id)
    album_id = new_id()
    now = to_iso(now_local())
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO albums (id, name, description, group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (album_id, values["name"], values["description"], group_id, now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のアルバムがあります。別の名前にしてください。") from exc
    return get_album(album_id)


def update_album(album_id: str, payload: dict[str, Any], viewer: Principal | None = None) -> dict[str, Any]:
    current = get_album(album_id, viewer)
    values = _validate({**current, **payload})
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE albums SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (values["name"], values["description"], to_iso(now_local()), album_id),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のアルバムがあります。別の名前にしてください。") from exc
    return get_album(album_id)


def delete_album(album_id: str, viewer: Principal | None = None) -> None:
    """アルバムだけを消す。画像はライブラリに残る。"""
    get_album(album_id, viewer)
    with connect() as conn:
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))


# ── アルバムの画像 ──────────────────────────────────


def list_items(album_id: str, viewer: Principal | None = None) -> list[dict[str, Any]]:
    get_album(album_id, viewer)
    with connect() as conn:
        rows = conn.execute(
            "SELECT x.added_at, i.* FROM album_items x JOIN images i ON i.id = x.image_id"
            " WHERE x.album_id = ? ORDER BY x.added_at DESC, i.captured_at DESC",
            (album_id,),
        ).fetchall()
    result = []
    for row in rows:
        result.append({
            "image": images._to_record(row),
            "added_at": row["added_at"],
        })
    return result


def _ids(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("画像を 1 枚以上選んでください。")
    if len(value) > 10000:
        raise ValueError("一度に扱えるのは 10,000 枚までです。")
    return [str(v) for v in value]


def add_items(album_id: str, image_ids: object, viewer: Principal | None = None) -> dict[str, int]:
    """追加する。すでに入っている画像はそのままにする。

    アルバムと同じグループの画像だけを入れる。別のグループの画像を入れると、
    そのグループに所属しない人にアルバム経由で見えてしまうため。
    """
    album = get_album(album_id, viewer)
    ids = _ids(image_ids)
    now = to_iso(now_local())
    added = 0
    with connect() as conn:
        for image_id in ids:
            row = conn.execute("SELECT group_id FROM images WHERE id = ?", (image_id,)).fetchone()
            if row is None or row["group_id"] != album["group_id"]:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO album_items (album_id, image_id, added_at) VALUES (?, ?, ?)",
                (album_id, image_id, now),
            )
            added += cur.rowcount
        _touch(conn, album_id)
    return {"added": added, "skipped": len(ids) - added}


def remove_items(album_id: str, image_ids: object, viewer: Principal | None = None) -> int:
    get_album(album_id, viewer)
    ids = _ids(image_ids)
    removed = 0
    with connect() as conn:
        for image_id in ids:
            cur = conn.execute("DELETE FROM album_items WHERE album_id = ? AND image_id = ?", (album_id, image_id))
            removed += cur.rowcount
        _touch(conn, album_id)
    return removed


def export_zip(album_id: str, viewer: Principal | None = None) -> tuple[str, BinaryIO]:
    """アルバムの画像をまとめて ZIP にする（フォルダは作らない）。"""
    album = get_album(album_id, viewer)
    items = list_items(album_id, viewer)
    if not items:
        raise ValueError("アルバムに画像がありません。ライブラリから画像を追加してください。")
    entries = []
    for item in items:
        record = item["image"]
        try:
            key = images.image_key(record["id"])
        except NotFoundError:
            continue
        entries.append((images.download_name(record, key), key))
    name = images.safe_name(album["name"]) or "album"
    return f"{name}.zip", images.build_zip(entries)
