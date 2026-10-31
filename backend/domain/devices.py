"""デバイス（Kazami 端末）の登録と認証。

流れ（共有の鍵（PSK）は使わない）:
1. 管理者がデバイスを作り、登録 QR を発行する。QR には接続先と、1 回限り・10 分で切れる登録トークンだけを入れる
2. Kazami は QR を読み、端末の中で署名鍵（P-256）を作る。公開鍵を登録トークンと一緒に、署名付きで送る
3. 起動のたびに、サーバーが出したチャレンジに署名してアクセストークンをもらう。
   一緒に、自分の設定（ルームID・シグナリング URL）を受け取る

秘密鍵は端末の外に出ない（実機では Secure Enclave の中）。サーバーが持つのは公開鍵だけなので、
サーバーのデータが漏れても端末になりすませない。
トークン・チャレンジは Valkey に TTL 付きで置く。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from core.db import connect
from core.kv import get_store
from domain import rooms
from domain.common import NotFoundError, new_id, now_local, optional_text, require_text, to_iso

ENROLL_TOKEN_TTL_SECONDS = 300
CHALLENGE_TTL_SECONDS = 300
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# 署名する中身の並び。Kazami 側（DeviceEnrollment.swift）と必ずそろえる
_ENROLL_LABEL = b"kazayomi-enroll-v1"
_AUTH_LABEL = b"kazayomi-auth-v1"
# 登録 QR に入れる接続先の決まり。Kazami 側（DeviceEnrollment.swift の parse）と必ずそろえる
_API_HOST_PATTERN = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")
_API_HOST_MAX_LENGTH = 100


class DeviceAuthError(PermissionError):
    """登録・認証に失敗した。api 層で 401 にする。理由は端末にも利用者にも細かく出さない。"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SELECT = """
SELECT d.*, c.name AS room_name, c.ayame_room_id AS ayame_room_id, c.group_id AS group_id, g.name AS group_name
FROM devices d
LEFT JOIN rooms c ON c.id = d.room_id
LEFT JOIN groups g ON g.id = c.group_id
"""


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "room_id": row["room_id"],
        "room_name": row["room_name"] or "",
        "ayame_room_id": row["ayame_room_id"] or "",
        "group_id": row["group_id"],
        "group_name": row["group_name"] or "",
        "device_id": row["device_id"] or "",
        "enrolled": bool(row["public_key"]),
        "enrolled_at": row["enrolled_at"],
        "last_seen_at": row["last_seen_at"],
        "last_ip": row["last_ip"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ── マスター ──────────────────────────────────────


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    room_id = str(payload.get("room_id") or "") or None
    if room_id:
        rooms.get_room(room_id)  # 無ければ NotFoundError
    return {
        "name": require_text(payload.get("name"), "デバイス名", max_length=100),
        "room_id": room_id,
        "note": optional_text(payload.get("note"), "メモ"),
    }


def list_devices() -> list[dict[str, Any]]:
    with connect() as conn:
        return [_record(r) for r in conn.execute(_SELECT + " ORDER BY d.name").fetchall()]


def get_device(row_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE d.id = ?", (row_id,)).fetchone()
    if row is None:
        raise NotFoundError("デバイスが見つかりません。")
    return _record(row)


def _find_by_device_id(device_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(_SELECT + " WHERE d.device_id = ?", (device_id,)).fetchone()


def create_device(payload: dict[str, Any]) -> dict[str, Any]:
    values = _validate(payload)
    row_id = new_id()
    now = to_iso(now_local())
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO devices (id, name, room_id, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (row_id, values["name"], values["room_id"], values["note"], now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のデバイスがあります。") from exc
    return get_device(row_id)


def update_device(row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    get_device(row_id)
    values = _validate(payload)
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE devices SET name = ?, room_id = ?, note = ?, updated_at = ? WHERE id = ?",
                (values["name"], values["room_id"], values["note"], to_iso(now_local()), row_id),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じ名前のデバイスがあります。") from exc
    return get_device(row_id)


def delete_device(row_id: str) -> dict[str, Any]:
    device = get_device(row_id)
    with connect() as conn:
        conn.execute("DELETE FROM devices WHERE id = ?", (row_id,))
    return device


def clear_enrollment(row_id: str) -> dict[str, Any]:
    """登録を外す。端末は次の起動から認証できなくなり、QR で登録し直す必要がある。

    端末をなくしたとき・入れ替えるときに使う。発行済みのアクセストークンは期限まで残るが、
    認証 Webhook（M4）は毎回この表を見るので、ルームには入れなくなる。
    """
    get_device(row_id)
    with connect() as conn:
        conn.execute(
            "UPDATE devices SET device_id = NULL, public_key = NULL, enrolled_at = NULL, updated_at = ? WHERE id = ?",
            (to_iso(now_local()), row_id),
        )
    return get_device(row_id)


# ── 登録 ──────────────────────────────────────────


def issue_enrollment(row_id: str) -> dict[str, Any]:
    """登録 QR に入れる、1 回限りの登録トークンを発行する。"""
    device = get_device(row_id)
    token = secrets.token_urlsafe(24)
    get_store().set(f"enroll:{_hash(token)}", device["id"], ENROLL_TOKEN_TTL_SECONDS)
    expires_at = now_local() + timedelta(seconds=ENROLL_TOKEN_TTL_SECONDS)
    return {"token": token, "name": device["name"], "expires_at": to_iso(expires_at)}


def api_origin(url: str) -> str:
    """登録 QR に入れる接続先を、https://ホスト[:ポート] の形にそろえる。

    Kazami はこの形のものしか受け付けない（パス・クエリ・ユーザー名付き・日本語や長すぎるホスト名・
    IPv6 アドレスは断る）。合わなければ ValueError。
    """
    text = url.strip()
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL の形式が正しくありません。") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise ValueError("https:// か http:// で始めてください。")
    if "?" in text or "#" in text or "@" in parts.netloc or parts.path not in ("", "/"):
        raise ValueError("パスやクエリを付けず、https://ホスト[:ポート] の形にしてください。")
    host = (parts.hostname or "").lower()
    if (not text.isascii() or not host or len(host) > _API_HOST_MAX_LENGTH or not _API_HOST_PATTERN.match(host)
            or any(len(label) > 63 for label in host.split("."))):
        raise ValueError("ホスト名は英数字・-・. で 100 文字までにしてください（IPv6 アドレスは使えません）。")
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def enrollment_qr_text(api_url: str, issued: dict[str, Any]) -> str:
    """登録 QR の中身（v / api / token / name）。秘密は入れない。
    日本語の名前を \\uXXXX にすると Kazami の長さの上限（1,024 バイト）に近づくので、そのまま入れる"""
    payload = {"v": 1, "api": api_url, "token": issued["token"], "name": issued["name"]}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_b64(value: object, label: str) -> bytes:
    try:
        return base64.b64decode(str(value or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DeviceAuthError(f"{label}の形式が正しくありません。") from exc


def _load_public_key(raw: bytes) -> ec.EllipticCurvePublicKey:
    # CryptoKit の x963Representation（0x04 + x + y、65 バイト）を受け付ける
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise DeviceAuthError("公開鍵の形式が正しくありません。") from exc


def _verify(public_key: ec.EllipticCurvePublicKey, signature: bytes, message: bytes) -> bool:
    try:
        public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


def enroll_message(token: str, device_id: str, public_key: bytes) -> bytes:
    return b"\n".join([_ENROLL_LABEL, token.encode(), device_id.encode(), public_key])


def auth_message(challenge: str, device_id: str) -> bytes:
    return b"\n".join([_AUTH_LABEL, challenge.encode(), device_id.encode()])


def _require_device_id(value: object) -> str:
    device_id = str(value or "")
    if not _DEVICE_ID_PATTERN.match(device_id):
        raise DeviceAuthError("デバイスIDの形式が正しくありません。")
    return device_id


def enroll(payload: dict[str, Any], *, ip: str = "") -> dict[str, Any]:
    token = str(payload.get("token") or "")
    device_id = _require_device_id(payload.get("device_id"))
    public_key_raw = _decode_b64(payload.get("device_pub"), "公開鍵")
    signature = _decode_b64(payload.get("signature"), "署名")
    public_key = _load_public_key(public_key_raw)

    store = get_store()
    key = f"enroll:{_hash(token)}"
    row_id = store.get(key) if token else None
    if row_id is None:
        raise DeviceAuthError("登録用の QR コードの期限が切れているか、使用済みです。kazayomi で発行し直してください。")
    # 秘密鍵を持っていることを確かめてから、トークンを使い切る（違う署名で叩かれてもトークンを潰さない）
    if not _verify(public_key, signature, enroll_message(token, device_id, public_key_raw)):
        raise DeviceAuthError("署名を確認できませんでした。")
    if store.pop(key) is None:
        raise DeviceAuthError("この QR コードはすでに使われています。")

    existing = _find_by_device_id(device_id)
    if existing is not None and existing["id"] != row_id:
        raise ValueError(f"この端末は別のデバイス「{existing['name']}」に登録されています。先にそちらの登録を外してください。")
    now = to_iso(now_local())
    with connect() as conn:
        conn.execute(
            "UPDATE devices SET device_id = ?, public_key = ?, enrolled_at = ?, last_seen_at = ?, last_ip = ?, updated_at = ?"
            " WHERE id = ?",
            (device_id, base64.b64encode(public_key_raw).decode(), now, now, ip, now, row_id),
        )
    device = get_device(row_id)
    return {"device_id": device_id, "name": device["name"]}


# ── 認証 ──────────────────────────────────────────


def issue_challenge(payload: dict[str, Any]) -> dict[str, Any]:
    device_id = _require_device_id(payload.get("device_id"))
    row = _find_by_device_id(device_id)
    if row is None or not row["public_key"]:
        # 登録が外れていることは端末に伝える（QR で登録し直してもらうため）
        raise DeviceAuthError("この端末は登録されていません。kazayomi で登録用の QR コードを発行して、読み取ってください。")
    challenge = secrets.token_hex(32)
    get_store().set(f"challenge:{device_id}", challenge, CHALLENGE_TTL_SECONDS)
    return {"challenge": challenge}


def issue_token(payload: dict[str, Any], *, ttl_seconds: int, default_signaling_url: str, ip: str = "") -> dict[str, Any]:
    device_id = _require_device_id(payload.get("device_id"))
    signature = _decode_b64(payload.get("signature"), "署名")
    store = get_store()
    challenge = store.get(f"challenge:{device_id}")
    row = _find_by_device_id(device_id)
    if challenge is None or row is None or not row["public_key"]:
        raise DeviceAuthError("認証の期限が切れました。もう一度やり直してください。")
    public_key = _load_public_key(base64.b64decode(row["public_key"]))
    if not _verify(public_key, signature, auth_message(challenge, device_id)):
        raise DeviceAuthError("署名を確認できませんでした。")
    # チャレンジは 1 回限り。同じ署名を送り直されても使えないようにする
    if store.pop(f"challenge:{device_id}") is None:
        raise DeviceAuthError("認証の期限が切れました。もう一度やり直してください。")

    access_token = secrets.token_urlsafe(32)
    store.set(f"device-token:{_hash(access_token)}", json.dumps({"device_id": device_id, "row_id": row["id"]}), ttl_seconds)
    now = to_iso(now_local())
    with connect() as conn:
        conn.execute("UPDATE devices SET last_seen_at = ?, last_ip = ? WHERE id = ?", (now, ip, row["id"]))

    device = get_device(row["id"])
    room = rooms.get_room(device["room_id"]) if device["room_id"] else None
    return {
        "access_token": access_token,
        "expires_in": ttl_seconds,
        "device_id": device_id,
        "name": device["name"],
        # ルームが未設定なら、端末は「ルーム未設定」と出して待つ
        "room": {"id": room["id"], "name": room["name"], "ayame_room_id": room["ayame_room_id"]} if room else None,
        "signaling_url": room["signaling_url"] if room else default_signaling_url,
        # Ayame に register するときの signalingKey。認証 Webhook がこれで端末を確かめる
        "signaling_key": access_token,
        # 本体の撮像ボタンで撮った画像を /api/devices/images に送れるか（ゲストのルームは False）
        "can_upload_captures": True,
    }


def resolve_access_token(token: str) -> dict[str, Any] | None:
    """アクセストークンから、今も登録されているデバイスを引く。登録を外した端末は None。"""
    if not token:
        return None
    raw = get_store().get(f"device-token:{_hash(token)}")
    if raw is None:
        return None
    data = json.loads(raw)
    row = _find_by_device_id(data["device_id"])
    if row is None or row["id"] != data["row_id"] or not row["public_key"]:
        return None
    return _record(row)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
