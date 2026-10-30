"""サーバ（Ayame のシグナリングサーバ）。ルームはどれか 1 つのサーバを使う。

1 つを「既定のサーバ」にできる。サーバを選んでいないルームは既定のサーバを使う。
既定のサーバもなければ、そのルームにはつなげない（画面にそう出す）。

種類（kind）:
- ayame: Ayame だけ。ICE サーバは Ayame から渡らず、ブラウザと Kazami が既定の STUN を使う
- cloudflare: シグナリングは Ayame のまま。入室のたびに Cloudflare の TURN キーで認証情報を発行して渡す（turn.py）
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit

from core.db import connect
from domain.common import NotFoundError, new_id, now_local, optional_text, require_text, to_iso

KINDS = ("ayame", "cloudflare")


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "signaling_url": row["signaling_url"],
        "kind": row["kind"],
        "turn_key_id": row["turn_key_id"],
        # API トークンは返さない（一覧はグループ管理者も見る）。設定済みかどうかだけ
        "turn_api_token_set": bool(row["turn_api_token"]),
        "note": row["note"],
        "is_default": bool(row["is_default"]),
        "room_count": row["room_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


_SELECT = "SELECT s.*, (SELECT COUNT(*) FROM rooms c WHERE c.server_id = s.id) AS room_count FROM servers s"


def _validate(payload: dict[str, Any], current_token: str = "") -> dict[str, Any]:
    """current_token は編集前の API トークン。turn_api_token を空で送ったときは、それをそのまま使う。"""
    url = require_text(payload.get("signaling_url"), "シグナリングURL", max_length=500)
    parsed = urlsplit(url)
    if parsed.scheme not in ("ws", "wss") or not parsed.netloc:
        raise ValueError("シグナリングURLは ws:// か wss:// で始まる URL にしてください（例: wss://ayame.example.com/signaling）。")
    kind = str(payload.get("kind") or "ayame")
    if kind not in KINDS:
        raise ValueError("サーバの種類が正しくありません。")
    key_id = token = ""
    if kind == "cloudflare":
        key_id = require_text(payload.get("turn_key_id"), "TURN キー ID", max_length=200)
        token = optional_text(payload.get("turn_api_token"), "API トークン", max_length=500) or current_token
        if not token:
            raise ValueError("API トークンを入力してください。")
    return {
        "name": require_text(payload.get("name"), "サーバ名", max_length=100),
        "signaling_url": url,
        "kind": kind,
        "turn_key_id": key_id,
        "turn_api_token": token,
        "note": optional_text(payload.get("note"), "メモ"),
        "is_default": bool(payload.get("is_default", False)),
    }


def list_servers() -> list[dict[str, Any]]:
    with connect() as conn:
        return [_record(r) for r in conn.execute(_SELECT + " ORDER BY s.is_default DESC, s.name").fetchall()]


def default_server() -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE s.is_default = 1").fetchone()
    return _record(row) if row else None


def _set_default(conn: sqlite3.Connection, server_id: str, is_default: bool) -> None:
    """既定は 1 つだけ。既定にするときは、ほかの既定を外してから付ける。"""
    if is_default:
        conn.execute("UPDATE servers SET is_default = 0 WHERE is_default = 1 AND id != ?", (server_id,))
    conn.execute("UPDATE servers SET is_default = ? WHERE id = ?", (int(is_default), server_id))


def get_server(server_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE s.id = ?", (server_id,)).fetchone()
    if row is None:
        raise NotFoundError("サーバが見つかりません。")
    return _record(row)


def _turn_token(server_id: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT turn_api_token FROM servers WHERE id = ?", (server_id,)).fetchone()
    return row[0] if row else ""


def ice_server_config(ayame_room_id: str) -> dict[str, str] | None:
    """そのルームが使うサーバの TURN 設定（cloudflare のときだけ）。ルームの登録がない（ゲストの一時的なルームなど）ときは既定のサーバ。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, kind, turn_key_id, turn_api_token, updated_at FROM servers WHERE id = COALESCE("
            " (SELECT server_id FROM rooms WHERE ayame_room_id = ?),"
            " (SELECT id FROM servers WHERE is_default = 1))",
            (ayame_room_id,),
        ).fetchone()
    if row is None or row["kind"] != "cloudflare":
        return None
    return {"server_id": row["id"], "key_id": row["turn_key_id"], "api_token": row["turn_api_token"],
            "updated_at": row["updated_at"]}


def create_server(payload: dict[str, Any]) -> dict[str, Any]:
    values = _validate(payload)
    server_id = new_id()
    now = to_iso(now_local())
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO servers (id, name, signaling_url, kind, turn_key_id, turn_api_token, note, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (server_id, values["name"], values["signaling_url"], values["kind"], values["turn_key_id"],
                 values["turn_api_token"], values["note"], now, now),
            )
            _set_default(conn, server_id, values["is_default"])
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のサーバがあります。") from exc
    invalidate_origin_cache()
    return get_server(server_id)


def update_server(server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_server(server_id)
    values = _validate({"is_default": current["is_default"], **payload}, current_token=_turn_token(server_id))
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE servers SET name = ?, signaling_url = ?, kind = ?, turn_key_id = ?, turn_api_token = ?, note = ?,"
                " updated_at = ? WHERE id = ?",
                (values["name"], values["signaling_url"], values["kind"], values["turn_key_id"], values["turn_api_token"],
                 values["note"], to_iso(now_local()), server_id),
            )
            _set_default(conn, server_id, values["is_default"])
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のサーバがあります。") from exc
    invalidate_origin_cache()
    return get_server(server_id)


def delete_server(server_id: str) -> None:
    server = get_server(server_id)
    if server["room_count"]:
        raise ValueError(f"このサーバを使うルームが {server['room_count']} 件あるため削除できません。先にルームのサーバを変えてください。")
    with connect() as conn:
        conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    invalidate_origin_cache()


# ── CSP 用のシグナリング Origin ─────────────────────
# レスポンスのたびに DB を読まないよう短く覚えておく。worker が複数あると
# 他の worker での登録は即時には反映されないため、期限を短くしてある。
_ORIGIN_CACHE_SECONDS = 5.0
_origin_cache: tuple[float, list[str]] | None = None


def _origin_of(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("ws", "wss") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def signaling_origins() -> list[str]:
    global _origin_cache
    now = time.monotonic()
    if _origin_cache is None or now - _origin_cache[0] > _ORIGIN_CACHE_SECONDS:
        try:
            with connect() as conn:
                urls = [row[0] for row in conn.execute("SELECT DISTINCT signaling_url FROM servers")]
        except RuntimeError:
            urls = []  # DB の初期化前（起動直後）
        _origin_cache = (now, urls)
    origins: list[str] = []
    for url in _origin_cache[1]:
        origin = _origin_of(url)
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def invalidate_origin_cache() -> None:
    global _origin_cache
    _origin_cache = None
