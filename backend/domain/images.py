"""撮像した画像の保存・一覧・更新・削除。

画像本体は `images/YYYYMMDD/<id>.<ext>`、サムネイルは `thumbs/<id>.jpg` のキーで、
rustfs（S3 互換）に置く（core/blobstore.py。設定が無ければ DATA_DIR の下）。メタデータは SQLite。タグは一覧表示用に JSON でも持ち、絞り込み用に image_tags にも入れる。
タグは表記ゆれ（全角・半角、大文字・小文字）を同じものとして扱う（image_tags.tag_key で比べる）。
画像に描いた図形（markers。楕円・多角形・吹き出し）は、画像の幅・高さに対する割合で持つ。
"""
from __future__ import annotations

import io
import json
import logging
import math
import sqlite3
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from core.blobstore import BlobNotFound, get_blobstore
from core.db import connect
from domain.access import Principal
from domain.common import (
    MAX_TAGS,
    NotFoundError,
    dumps,
    new_id,
    normalize_tags,
    now_local,
    optional_text,
    tag_key,
    to_iso,
)

logger = logging.getLogger(__name__)

ImageSource = Literal["camera", "upload"]
TagMode = Literal["add", "replace", "remove"]

# 受け付ける形式と保存時の拡張子。ブラウザで表示できるものに限る。
_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
CONTENT_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_MAX_PIXELS = 100_000_000
_MAX_LIST_LIMIT = 2000


@dataclass
class ImageConfig:
    thumbnail_size: int = 320
    max_upload_bytes: int = 30 * 1024 * 1024


_config: ImageConfig | None = None


def configure(config: ImageConfig) -> None:
    global _config
    _config = config


def _cfg() -> ImageConfig:
    if _config is None:
        raise RuntimeError("images.configure() has not been called")
    return _config


def _to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room_name": row["room_name"],
        "group_id": row["group_id"],
        "captured_by": row["captured_by"],
        "captured_at": row["captured_at"],
        "date_key": row["date_key"],
        "source": row["source"],
        "source_name": row["source_name"],
        "width": row["width"],
        "height": row["height"],
        "size_bytes": row["size_bytes"],
        "tags": json.loads(row["tags"]),
        "markers": json.loads(row["markers"]),
        "note": row["note"],
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _write_tags(conn: sqlite3.Connection, image_id: str, tags: list[str]) -> None:
    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
    conn.executemany(
        "INSERT INTO image_tags (image_id, tag, tag_key) VALUES (?, ?, ?)",
        [(image_id, t, tag_key(t)) for t in tags],
    )
    conn.execute("UPDATE images SET tags = ? WHERE id = ?", (dumps(tags), image_id))


# ── 保存 ────────────────────────────────────────────


def save_image(
    data: bytes,
    *,
    source: ImageSource,
    group_id: str,
    captured_at: datetime | None = None,
    room: dict[str, Any] | None = None,
    captured_by: str = "",
    source_name: str = "",
    tags: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    cfg = _cfg()
    if not data:
        raise ValueError("画像が空です。撮り直してください。")
    if len(data) > cfg.max_upload_bytes:
        raise ValueError(f"画像が大きすぎます（上限 {cfg.max_upload_bytes // (1024 * 1024)}MB）。")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format or ""
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("画像として読み込めませんでした。JPEG・PNG・WebP のファイルを指定してください。") from exc
    if fmt not in _FORMATS:
        raise ValueError("対応していない形式です。JPEG・PNG・WebP のファイルを指定してください。")
    if width * height > _MAX_PIXELS:
        raise ValueError("画像の画素数が大きすぎます。")

    _check_quota(group_id, len(data))
    shot_at = (captured_at or now_local()).astimezone()
    date_key = shot_at.strftime("%Y%m%d")
    image_id = new_id()
    key = f"images/{date_key}/{image_id}.{_FORMATS[fmt]}"
    store = get_blobstore()
    store.put(key, data, CONTENT_TYPES[f".{_FORMATS[fmt]}"])

    try:
        thumbnail = _make_thumbnail(data, cfg.thumbnail_size)
        store.put(_thumb_key(image_id), thumbnail, "image/jpeg")
        tag_list = normalize_tags(tags)
        now = to_iso(now_local())
        with connect() as conn:
            conn.execute(
                "INSERT INTO images (id, room_id, room_name, group_id, captured_by, captured_at, date_key, source,"
                " source_name, path, width, height, size_bytes, thumb_bytes, tags, note, favorite, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    image_id,
                    room["id"] if room else None,
                    room["name"] if room else "",
                    group_id,
                    captured_by,
                    to_iso(shot_at),
                    date_key,
                    source,
                    optional_text(source_name, "ファイル名", max_length=255),
                    key,
                    width,
                    height,
                    len(data),
                    len(thumbnail),
                    dumps(tag_list),
                    optional_text(note, "メモ"),
                    now,
                    now,
                ),
            )
            _write_tags(conn, image_id, tag_list)
    except Exception:
        # メタデータが入らなかったファイルは誰からも見えなくなるので消しておく
        store.delete(key)
        store.delete(_thumb_key(image_id))
        raise
    return get_image(image_id)


class QuotaExceededError(ValueError):
    """グループの容量の上限を超える。api 層で 507 にする。"""


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _check_quota(group_id: str, adding: int) -> None:
    """保存すると容量の上限を超えるなら止める。上限がない（NULL）グループは止めない。

    同時に何枚も届くと少しだけ超えることがあるが、上限の目安としてはそれで足りる
    （正確に止めるために書き込みを 1 本にすると、撮像が詰まるため）。
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT g.name, g.quota_bytes,"
            " (SELECT COALESCE(SUM(i.size_bytes + i.thumb_bytes), 0) FROM images i WHERE i.group_id = g.id) AS used"
            " FROM groups g WHERE g.id = ?",
            (group_id,),
        ).fetchone()
    if row is None or row["quota_bytes"] is None:
        return
    if row["used"] + adding > row["quota_bytes"]:
        raise QuotaExceededError(
            f"グループ「{row['name']}」の容量の上限（{format_bytes(row['quota_bytes'])}）に達しているため、画像を保存できません"
            f"（使用中 {format_bytes(row['used'])}）。不要な画像を消すか、管理者に上限を上げてもらってください。"
        )


def _thumb_key(image_id: str) -> str:
    return f"thumbs/{image_id}.jpg"


def _make_thumbnail(data: bytes, size: int) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        # EXIF の向きを反映しておかないと、iPhone で撮った縦の写真が横向きの一覧になる
        thumb = ImageOps.exif_transpose(img)
        thumb.thumbnail((size, size))
        if thumb.mode not in ("RGB", "L"):
            thumb = thumb.convert("RGB")
        buffer = io.BytesIO()
        thumb.save(buffer, "JPEG", quality=82)
        return buffer.getvalue()


# ── 取得 ────────────────────────────────────────────


# viewer に None を渡すのは、ログインしたユーザー以外（Kazami からの撮像など）が扱うときだけ。
# 見られないグループの画像は「無い」と答える（存在を伏せる）。


def _get_row(image_id: str, viewer: Principal | None) -> sqlite3.Row:
    with connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None or (viewer is not None and not viewer.can_see_group(row["group_id"])):
        raise NotFoundError("画像が見つかりません。削除された可能性があります。")
    return row


def get_image(image_id: str, viewer: Principal | None = None) -> dict[str, Any]:
    return _to_record(_get_row(image_id, viewer))


def image_key(image_id: str, viewer: Principal | None = None) -> str:
    """画像本体のキー（images/YYYYMMDD/<id>.<拡張子>）。"""
    return _get_row(image_id, viewer)["path"]


def content_type_of(key: str) -> str:
    return CONTENT_TYPES.get(PurePosixPath(key).suffix.lower(), "application/octet-stream")


def open_image(image_id: str, viewer: Principal | None = None) -> tuple[Iterator[bytes], int, str]:
    """画像本体を少しずつ読む。（中身, 大きさ, Content-Type）"""
    key = image_key(image_id, viewer)
    try:
        chunks, size = get_blobstore().stream(key)
    except BlobNotFound as exc:
        raise NotFoundError("画像のファイルが見つかりません。管理者に連絡してください。") from exc
    return chunks, size, content_type_of(key)


def read_thumbnail(image_id: str, viewer: Principal | None = None) -> bytes:
    key = image_key(image_id, viewer)
    store = get_blobstore()
    try:
        return store.get(_thumb_key(image_id))
    except BlobNotFound:
        # 古いデータや作成失敗に備え、無ければその場で作る
        try:
            thumb = _make_thumbnail(store.get(key), _cfg().thumbnail_size)
        except BlobNotFound as exc:
            raise NotFoundError("画像のファイルが見つかりません。管理者に連絡してください。") from exc
        store.put(_thumb_key(image_id), thumb, "image/jpeg")
        return thumb


def _visible_ids(conn: sqlite3.Connection, image_ids: list[str], viewer: Principal | None) -> list[str]:
    """一括操作の対象のうち、存在して、viewer が見られるものだけを残す（順は保つ）。"""
    found: dict[str, str] = {}
    for start in range(0, len(image_ids), 500):
        chunk = image_ids[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        for row in conn.execute(f"SELECT id, group_id FROM images WHERE id IN ({marks})", chunk):
            found[row["id"]] = row["group_id"]
    return [i for i in image_ids if i in found and (viewer is None or viewer.can_see_group(found[i]))]


@dataclass
class ImageFilter:
    room_id: str | None = None  # "none" はルームなし（手動の取り込みと、ルームを消した画像）
    room_name: str | None = None  # room_id="none" のとき、撮像時点の名前で分ける（"" は手動の取り込み）
    group_ids: list[str] | None = None  # 見られるグループ。None は絞らない
    date_from: str | None = None  # YYYYMMDD
    date_to: str | None = None
    tags: list[str] | None = None  # いずれかのタグを持つもの（表記ゆれは同じものとみなす）
    favorite: bool | None = None


def _where(flt: ImageFilter) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if flt.group_ids is not None:
        if not flt.group_ids:
            clauses.append("0")
        else:
            clauses.append(f"i.group_id IN ({','.join('?' for _ in flt.group_ids)})")
            params.extend(flt.group_ids)
    if flt.room_id == "none":
        clauses.append("i.room_id IS NULL")
        if flt.room_name is not None:
            clauses.append("i.room_name = ?")
            params.append(flt.room_name)
    elif flt.room_id:
        clauses.append("i.room_id = ?")
        params.append(flt.room_id)
    if flt.date_from:
        clauses.append("i.date_key >= ?")
        params.append(flt.date_from)
    if flt.date_to:
        clauses.append("i.date_key <= ?")
        params.append(flt.date_to)
    if flt.tags:
        keys = list(dict.fromkeys(tag_key(t) for t in flt.tags))
        marks = ",".join("?" for _ in keys)
        clauses.append(f"EXISTS (SELECT 1 FROM image_tags t WHERE t.image_id = i.id AND t.tag_key IN ({marks}))")
        params.extend(keys)
    if flt.favorite is not None:
        clauses.append("i.favorite = ?")
        params.append(1 if flt.favorite else 0)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_images(flt: ImageFilter, *, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, _MAX_LIST_LIMIT))
    offset = max(0, offset)
    where, params = _where(flt)
    with connect() as conn:
        (total,) = conn.execute(f"SELECT COUNT(*) FROM images i{where}", params).fetchone()
        rows = conn.execute(
            f"SELECT i.* FROM images i{where} ORDER BY i.captured_at DESC, i.id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    items = [_to_record(row) for row in rows]
    next_offset = offset + len(items)
    return {"items": items, "total": total, "next_offset": next_offset if next_offset < total else None}


def summary(date_from: str | None = None, date_to: str | None = None,
            group_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """ルーム別・日付別の件数。ライブラリ左のツリーに使う。"""
    where, params = _where(ImageFilter(date_from=date_from, date_to=date_to, group_ids=group_ids))
    with connect() as conn:
        rows = conn.execute(
            "SELECT i.room_id, COALESCE(c.name, i.room_name) AS room_name, i.date_key, COUNT(*) AS count"
            f" FROM images i LEFT JOIN rooms c ON c.id = i.room_id{where}"
            " GROUP BY i.room_id, COALESCE(c.name, i.room_name), i.date_key"
            " ORDER BY room_name, i.date_key DESC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def tag_counts(group_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """使われているタグと枚数。表記ゆれはまとめ、いちばん多く使われている書き方で返す。"""
    where, params = _where(ImageFilter(group_ids=group_ids))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT t.tag_key, t.tag, COUNT(*) AS count FROM image_tags t JOIN images i ON i.id = t.image_id{where}"
            " GROUP BY t.tag_key, t.tag",
            params,
        ).fetchall()
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = merged.setdefault(row["tag_key"], {"tag": row["tag"], "count": 0, "best": 0})
        entry["count"] += row["count"]
        if row["count"] > entry["best"]:
            entry.update(tag=row["tag"], best=row["count"])
    result = [{"tag": e["tag"], "count": e["count"]} for e in merged.values()]
    result.sort(key=lambda e: (-e["count"], tag_key(e["tag"])))
    return result


# ── 図形（マーカー） ─────────────────────────────────

MAX_MARKERS = 100
MAX_POLYGON_POINTS = 500
MAX_CALLOUT_TEXT = 200
# 割合は小数 5 桁あれば 4000px の画像でも 0.04px の精度になる
_MARKER_DECIMALS = 5


def _ratio(value: object, name: str, *, low: float = -1.0, high: float = 2.0) -> float:
    """画像の幅・高さに対する割合。画像から少しはみ出すのは許す（枠の端に描いた図形のため）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"図形の {name} が数ではありません。")
    if not low <= value <= high:
        raise ValueError(f"図形の {name} が画像の範囲から外れています。")
    return round(float(value), _MARKER_DECIMALS)


def normalize_markers(value: object) -> list[dict[str, Any]]:
    """画像に描いた図形をそろえる。楕円（中心・幅・高さ・回転）、多角形（頂点）、吹き出し（指す先・中心・文字）を受け付ける。"""
    if not isinstance(value, list):
        raise ValueError("図形の形式が正しくありません。図形の一覧で指定してください。")
    if len(value) > MAX_MARKERS:
        raise ValueError(f"図形は 1 枚に {MAX_MARKERS} 個までです。")
    shapes: list[dict[str, Any]] = []
    for shape in value:
        if not isinstance(shape, dict):
            raise ValueError("図形の形式が正しくありません。")
        kind = shape.get("type")
        if kind == "ellipse":
            rotation = shape.get("rotation", 0)
            if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation):
                raise ValueError("図形の rotation が数ではありません。")
            shapes.append({
                "type": "ellipse",
                "x": _ratio(shape.get("x"), "x"),
                "y": _ratio(shape.get("y"), "y"),
                "width": _ratio(shape.get("width"), "width", low=0.0),
                "height": _ratio(shape.get("height"), "height", low=0.0),
                "rotation": round(float(rotation) % 360, _MARKER_DECIMALS),
            })
        elif kind == "polygon":
            points = shape.get("points")
            if not isinstance(points, list) or not 3 <= len(points) <= MAX_POLYGON_POINTS:
                raise ValueError(f"多角形の頂点は 3〜{MAX_POLYGON_POINTS} 個にしてください。")
            normalized = []
            for point in points:
                if not isinstance(point, dict):
                    raise ValueError("多角形の頂点の形式が正しくありません。")
                normalized.append({"x": _ratio(point.get("x"), "x"), "y": _ratio(point.get("y"), "y")})
            shapes.append({"type": "polygon", "points": normalized})
        elif kind == "callout":
            text = shape.get("text", "")
            if not isinstance(text, str):
                raise ValueError("吹き出しの文字が正しくありません。")
            text = text.strip()
            if len(text) > MAX_CALLOUT_TEXT:
                raise ValueError(f"吹き出しの文字は {MAX_CALLOUT_TEXT} 文字以内にしてください。")
            shapes.append({
                "type": "callout",
                "x": _ratio(shape.get("x"), "x"),
                "y": _ratio(shape.get("y"), "y"),
                "bx": _ratio(shape.get("bx"), "bx"),
                "by": _ratio(shape.get("by"), "by"),
                "text": text,
            })
        else:
            raise ValueError("図形の種類は ellipse（楕円）・polygon（多角形）・callout（吹き出し）です。")
    return shapes


# ── 更新 ────────────────────────────────────────────


def update_image(image_id: str, payload: dict[str, Any], viewer: Principal | None = None) -> dict[str, Any]:
    """指定された項目だけ変える（未指定の項目はそのまま）。"""
    get_image(image_id, viewer)
    with connect() as conn:
        if "tags" in payload:
            _write_tags(conn, image_id, normalize_tags(payload["tags"]))
        if "note" in payload:
            conn.execute("UPDATE images SET note = ? WHERE id = ?", (optional_text(payload["note"], "メモ"), image_id))
        if "favorite" in payload:
            conn.execute("UPDATE images SET favorite = ? WHERE id = ?", (1 if payload["favorite"] else 0, image_id))
        if "markers" in payload:
            conn.execute("UPDATE images SET markers = ? WHERE id = ?", (dumps(normalize_markers(payload["markers"])), image_id))
        conn.execute("UPDATE images SET updated_at = ? WHERE id = ?", (to_iso(now_local()), image_id))
    return get_image(image_id)


def batch_update_tags(image_ids: object, tags: object, mode: str, viewer: Principal | None = None) -> int:
    if mode not in ("add", "replace", "remove"):
        raise ValueError("タグの更新方法は add・replace・remove のいずれかです。")
    tag_list = normalize_tags(tags)
    if mode != "replace" and not tag_list:
        raise ValueError("タグを 1 つ以上指定してください。")
    ids = _validate_ids(image_ids)
    now = to_iso(now_local())
    updated = 0
    with connect() as conn:
        for image_id in _visible_ids(conn, ids, viewer):
            row = conn.execute("SELECT tags FROM images WHERE id = ?", (image_id,)).fetchone()
            if row is None:
                continue
            current: list[str] = json.loads(row["tags"])
            current_keys = {tag_key(t) for t in current}
            requested_keys = {tag_key(t) for t in tag_list}
            if mode == "add":
                next_tags = current + [t for t in tag_list if tag_key(t) not in current_keys]
            elif mode == "remove":
                next_tags = [t for t in current if tag_key(t) not in requested_keys]
            else:
                next_tags = tag_list
            if len(next_tags) > MAX_TAGS:
                raise ValueError(f"追加すると、タグが {MAX_TAGS} 個を超える画像があります（1 枚に {MAX_TAGS} 個まで）。")
            if next_tags != current:
                _write_tags(conn, image_id, next_tags)
                conn.execute("UPDATE images SET updated_at = ? WHERE id = ?", (now, image_id))
                updated += 1
    return updated


def _validate_ids(image_ids: object) -> list[str]:
    if not isinstance(image_ids, list) or not image_ids:
        raise ValueError("画像を 1 枚以上選んでください。")
    if len(image_ids) > 10000:
        raise ValueError("一度に扱えるのは 10,000 枚までです。")
    return [str(i) for i in image_ids]


def delete_images(image_ids: object, viewer: Principal | None = None) -> int:
    """画像を消す。アルバムからも外れる（外部キーの CASCADE）。"""
    ids = _validate_ids(image_ids)
    removed: list[tuple[str, str]] = []
    with connect() as conn:
        for image_id in _visible_ids(conn, ids, viewer):
            row = conn.execute("SELECT path FROM images WHERE id = ?", (image_id,)).fetchone()
            if row is None:
                continue
            conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
            removed.append((image_id, row["path"]))
    delete_files(removed)
    return len(removed)


def delete_files(removed: list[tuple[str, str]]) -> None:
    """画像とサムネイルのファイルを消す。removed は (画像 ID, 画像のキー) の一覧。

    ファイルは、メタデータを消し終えてから消す。ファイルが消せずに残っても、誰からも見えないだけで済む
    （逆にすると、メタデータだけ残って「ファイルが見つからない」画像ができる）
    """
    store = get_blobstore()
    for image_id, key in removed:
        try:
            store.delete(key)
            store.delete(_thumb_key(image_id))
        except Exception:
            logger.exception("failed to delete image files: %s", key)


def count_album_usage(image_ids: object, viewer: Principal | None = None) -> int:
    """削除の確認ダイアログで「アルバムからも外れる枚数」を出すため。"""
    with connect() as conn:
        ids = _visible_ids(conn, _validate_ids(image_ids), viewer)
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        (count,) = conn.execute(
            f"SELECT COUNT(DISTINCT image_id) FROM album_items WHERE image_id IN ({marks})", ids
        ).fetchone()
    return count


# ── ZIP ─────────────────────────────────────────────


def download_name(record: dict[str, Any], key: str) -> str:
    """ZIP やダウンロードで使うファイル名。撮像日時とルーム名で、何の画像か分かるようにする。"""
    stamp = record["captured_at"][:19].replace("-", "").replace(":", "").replace("T", "_")
    room = safe_name(record["room_name"]) or record["source"]
    return f"{stamp}_{room}_{record['id'][:8]}{PurePosixPath(key).suffix}"


def safe_name(value: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip())
    return keep.strip("._")[:60]


def build_zip(entries: list[tuple[str, str]]) -> BinaryIO:
    """(ZIP 内のパス, 画像のキー) の並びから ZIP を作る。

    大きくなりうるので、一定量を超えたらディスクに逃がす一時ファイルに書く。
    1 枚ずつ読んで書くので、メモリに載るのは 1 枚ぶんだけ。
    JPEG は圧縮しても縮まないので、ZIP_STORED にして CPU を使わない。
    """
    store = get_blobstore()
    buffer = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for arcname, key in entries:
            try:
                zf.writestr(arcname, store.get(key))
            except BlobNotFound:
                logger.warning("image file missing while zipping: %s", key)
    buffer.seek(0)
    return buffer


def zip_images(image_ids: object, viewer: Principal | None = None) -> BinaryIO:
    ids = _validate_ids(image_ids)
    entries: list[tuple[str, str]] = []
    for image_id in ids:
        try:
            record = get_image(image_id, viewer)
            key = image_key(image_id, viewer)
        except NotFoundError:
            continue
        entries.append((f"{record['date_key']}/{download_name(record, key)}", key))
    if not entries:
        raise ValueError("ダウンロードできる画像がありません。")
    return build_zip(entries)
