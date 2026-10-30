"""ゲストの一時的なルーム。

ログイン画面で「ゲストとして試す」を選んだ人には、Ayame Labo のように、1 人 1 つだけ一時的なルームを作る。
ゲストは Google ログインを使わず、ニックネームと利用規約への同意だけで始める。
- ルームも、そこに登録した Kazami も、DB ではなく Valkey に期限付きで置く。最後に使ってから
  GUEST_ROOM_TTL_SECONDS（既定 24 時間）たつか、「終了」すると消える
- 誰のルームかは、ゲストを始めたときに作る乱数（セッションの Cookie にだけある）を、秘密の鍵で HMAC にしたもので持つ。
  ニックネームも Valkey には置かない
- Kazami の登録・認証の手順（QR → 鍵の登録 → チャレンジ → トークン）はグループのデバイスと同じ。
  Kazami は、ゲストのルームかグループのルームかを気にしなくてよい（api/devices_api.py が振り分ける）
- グループのデバイスとして登録済みの Kazami は、ゲストの QR では登録できない（取り合わない）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any

from config.settings import get_settings
from core.kv import get_store
from domain import devices, rooms
from domain.access import Principal
from domain.common import NotFoundError, now_local, to_iso
from domain.devices import DeviceAuthError

ENROLL_TOKEN_TTL_SECONDS = devices.ENROLL_TOKEN_TTL_SECONDS
DEVICE_NAME = "Kazami（一時的なルーム）"


def _ttl() -> int:
    return get_settings().guest_room_ttl_seconds


def owner_of(viewer: Principal) -> str:
    """ルームの持ち主を表す値。ゲストの ID をそのまま Valkey に置かない。"""
    identity = viewer.subject or f"user:{viewer.email}"
    secret = (get_settings().session_secret or "local-development-only").encode()
    return hmac.new(secret, identity.encode(), hashlib.sha256).hexdigest()[:40]


def _load(room_id: str) -> dict[str, Any] | None:
    raw = get_store().get(f"guest-room:{room_id}")
    return json.loads(raw) if raw else None


def _save(room: dict[str, Any]) -> None:
    """保存し直すたびに期限を延ばす（最後に使ってから数える）。"""
    ttl = _ttl()
    room["expires_at"] = to_iso(now_local() + timedelta(seconds=ttl))
    store = get_store()
    store.set(f"guest-room:{room['id']}", json.dumps(room), ttl)
    store.set(f"guest-owner:{room['owner']}", room["id"], ttl)
    if room.get("device"):
        store.set(f"guest-device:{room['device']['device_id']}", room["id"], ttl)
    # 再開コードも、ルームと同じだけ延ばす
    code_key = store.get(f"guest-code-of:{room['owner']}")
    gid = store.get(f"guest-code:{code_key}") if code_key else None
    if code_key and gid:
        store.set(f"guest-code:{code_key}", gid, ttl)
        store.set(f"guest-code-of:{room['owner']}", code_key, ttl)


def _view(room: dict[str, Any]) -> dict[str, Any]:
    """画面に返す形。持ち主の値と端末の鍵は出さない。"""
    device = room.get("device")
    return {
        "id": room["id"],
        "ayame_room_id": room["ayame_room_id"],
        "created_at": room["created_at"],
        "expires_at": room["expires_at"],
        "ttl_seconds": _ttl(),
        "device": {"enrolled": True, "enrolled_at": device["enrolled_at"]} if device else None,
        "signaling_ready": bool(rooms.default_signaling_url()),
    }


def _own_room(viewer: Principal) -> dict[str, Any] | None:
    room_id = get_store().get(f"guest-owner:{owner_of(viewer)}")
    room = _load(room_id) if room_id else None
    return room if room and room["owner"] == owner_of(viewer) else None


def get_or_create(viewer: Principal) -> dict[str, Any]:
    """自分のルーム。なければ作る（1 人 1 ルーム）。開くたびに期限を延ばす。"""
    room = _own_room(viewer)
    if room is None:
        room_id = secrets.token_hex(8)
        room = {
            "id": room_id,
            "owner": owner_of(viewer),
            # 推測されないルーム ID。Ayame の認証 Webhook も、持ち主と登録した Kazami しか通さない
            "ayame_room_id": f"guest-{secrets.token_urlsafe(12)}",
            "created_at": to_iso(now_local()),
            "device": None,
        }
    _save(room)
    return _view(room)


def require_room(viewer: Principal) -> dict[str, Any]:
    room = _own_room(viewer)
    if room is None:
        raise NotFoundError("ルームが見つかりません。期限が切れたかもしれません。画面を開き直してください。")
    return room


def touch(viewer: Principal) -> dict[str, Any]:
    room = require_room(viewer)
    _save(room)
    return room


def end(viewer: Principal) -> None:
    """ルームを終える。登録した Kazami も使えなくなる（次の QR を待つ）。"""
    room = _own_room(viewer)
    if room is None:
        return
    store = get_store()
    store.pop(f"guest-room:{room['id']}")
    store.pop(f"guest-owner:{room['owner']}")
    if room.get("device"):
        store.pop(f"guest-device:{room['device']['device_id']}")


# ── 再開コード ───────────────────────────────────
# ログアウトしたり、別のブラウザから開いたりしても、同じルームに戻るためのコード（Zoom のパスコードのようなもの）。
# サーバにはコードそのものは置かず、鍵付きのハッシュ → ゲストの ID だけを、ルームと同じ期限で置く。
# コードそのものは、本人の「続きから使う」Cookie（署名付き・HttpOnly）にだけある
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 0/O・1/I など、見間違えやすい字は使わない
_CODE_LENGTH = 12  # 32 種類 × 12 文字 = 60 ビット。回数の制限と合わせて、当て推量では当たらない


def new_resume_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, _CODE_LENGTH, 4))


def normalize_resume_code(code: object) -> str:
    """入力の揺れをならす（小文字、空白・ハイフンの有無）。"""
    return "".join(ch for ch in str(code or "").upper() if ch in _CODE_ALPHABET)


def _code_key(code: str) -> str:
    secret = (get_settings().session_secret or "local-development-only").encode()
    return hmac.new(secret, f"resume:{normalize_resume_code(code)}".encode(), hashlib.sha256).hexdigest()[:40]


def register_resume_code(viewer: Principal, code: str) -> None:
    """ゲストの再開コードを登録する（ゲストを始めたとき）。前のコードは使えなくする。"""
    store = get_store()
    owner = owner_of(viewer)
    previous = store.get(f"guest-code-of:{owner}")
    if previous:
        store.pop(f"guest-code:{previous}")
    key = _code_key(code)
    store.set(f"guest-code:{key}", viewer.subject.removeprefix("guest:"), _ttl())
    store.set(f"guest-code-of:{owner}", key, _ttl())


def resolve_resume_code(code: object) -> str | None:
    """再開コードから、ゲストの ID を引く。期限切れ・間違いは None。"""
    normalized = normalize_resume_code(code)
    if len(normalized) != _CODE_LENGTH:
        return None
    return get_store().get(f"guest-code:{_code_key(normalized)}")


# ── Kazami の登録と認証（グループのデバイス、domain/devices.py と同じ手順）─────────────

def has_enrollment_token(token: str) -> bool:
    return bool(token) and get_store().get(f"guest-enroll:{devices._hash(token)}") is not None


def has_device(device_id: str) -> bool:
    return _room_of_device(str(device_id or "")) is not None


def has_access_token(token: str) -> bool:
    return bool(token) and get_store().get(f"guest-device-token:{devices._hash(token)}") is not None


def release_device(device_id: str) -> None:
    """グループのデバイスとして登録し直した Kazami を、ゲストのルームから外す。"""
    room = _room_of_device(device_id)
    if room is not None:
        room["device"] = None
        _save(room)
        get_store().pop(f"guest-device:{device_id}")

def issue_enrollment(viewer: Principal) -> dict[str, Any]:
    room = touch(viewer)
    token = secrets.token_urlsafe(24)
    get_store().set(f"guest-enroll:{devices._hash(token)}", room["id"], ENROLL_TOKEN_TTL_SECONDS)
    return {
        "token": token,
        "name": DEVICE_NAME,
        "expires_at": to_iso(now_local() + timedelta(seconds=ENROLL_TOKEN_TTL_SECONDS)),
    }


def _room_of_device(device_id: str) -> dict[str, Any] | None:
    room_id = get_store().get(f"guest-device:{device_id}")
    room = _load(room_id) if room_id else None
    if room is None or not room.get("device") or room["device"]["device_id"] != device_id:
        return None
    return room


def enroll(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token") or "")
    device_id = devices._require_device_id(payload.get("device_id"))
    public_key_raw = devices._decode_b64(payload.get("device_pub"), "公開鍵")
    signature = devices._decode_b64(payload.get("signature"), "署名")
    public_key = devices._load_public_key(public_key_raw)

    store = get_store()
    key = f"guest-enroll:{devices._hash(token)}"
    room_id = store.get(key) if token else None
    if room_id is None:
        raise DeviceAuthError("登録用の QR コードの期限が切れているか、使用済みです。kazayomi で発行し直してください。")
    if not devices._verify(public_key, signature, devices.enroll_message(token, device_id, public_key_raw)):
        raise DeviceAuthError("署名を確認できませんでした。")
    existing = devices._find_by_device_id(device_id)
    if existing is not None and existing["public_key"]:
        # グループのデバイスを、ゲストのルームに取られないようにする（QR は使い切らない）
        raise ValueError(f"この端末はグループのデバイス「{existing['name']}」として登録されています。"
                         "ゲストのルームで使うには、先に管理者に登録を外してもらってください。")
    if store.pop(key) is None:
        raise DeviceAuthError("この QR コードはすでに使われています。")
    room = _load(room_id)
    if room is None:
        raise DeviceAuthError("ルームの期限が切れています。kazayomi を開き直して、QR を発行し直してください。")

    # 同じ端末が前に別のルームに登録されていたら、そちらからは外す（端末は 1 つのルームにだけつながる）
    previous = _room_of_device(device_id)
    if previous is not None and previous["id"] != room["id"]:
        previous["device"] = None
        _save(previous)
    # ルームに前の端末がいたら、その端末はつながらなくなる（1 ルーム 1 台）
    if room.get("device") and room["device"]["device_id"] != device_id:
        store.pop(f"guest-device:{room['device']['device_id']}")
    room["device"] = {
        "device_id": device_id,
        "public_key": base64.b64encode(public_key_raw).decode(),
        "enrolled_at": to_iso(now_local()),
    }
    _save(room)
    return {"device_id": device_id, "name": DEVICE_NAME}


def issue_challenge(payload: dict[str, Any]) -> dict[str, Any]:
    device_id = devices._require_device_id(payload.get("device_id"))
    if _room_of_device(device_id) is None:
        raise DeviceAuthError("この端末は登録されていません。kazayomi で登録用の QR コードを発行して、読み取ってください。")
    challenge = secrets.token_hex(32)
    get_store().set(f"guest-challenge:{device_id}", challenge, devices.CHALLENGE_TTL_SECONDS)
    return {"challenge": challenge}


def issue_token(payload: dict[str, Any], *, ttl_seconds: int) -> dict[str, Any]:
    device_id = devices._require_device_id(payload.get("device_id"))
    signature = devices._decode_b64(payload.get("signature"), "署名")
    store = get_store()
    challenge = store.get(f"guest-challenge:{device_id}")
    room = _room_of_device(device_id)
    if challenge is None or room is None:
        raise DeviceAuthError("認証の期限が切れました。もう一度やり直してください。")
    public_key = devices._load_public_key(base64.b64decode(room["device"]["public_key"]))
    if not devices._verify(public_key, signature, devices.auth_message(challenge, device_id)):
        raise DeviceAuthError("署名を確認できませんでした。")
    if store.pop(f"guest-challenge:{device_id}") is None:
        raise DeviceAuthError("認証の期限が切れました。もう一度やり直してください。")

    # 端末がつながってくるのも「使っている」ので、期限を延ばす
    _save(room)
    access_token = secrets.token_urlsafe(32)
    store.set(f"guest-device-token:{devices._hash(access_token)}",
              json.dumps({"device_id": device_id, "room_id": room["id"]}), min(ttl_seconds, _ttl()))
    return {
        "access_token": access_token,
        "expires_in": min(ttl_seconds, _ttl()),
        "device_id": device_id,
        "name": DEVICE_NAME,
        "room": {"id": room["id"], "name": "一時的なルーム", "ayame_room_id": room["ayame_room_id"]},
        "signaling_url": rooms.default_signaling_url(),
        "signaling_key": access_token,
        # ゲストのルームの画像は預からない。Kazami は本体の撮像ボタンを出さない（撮像はブラウザから）
        "can_upload_captures": False,
    }


def resolve_access_token(token: str) -> dict[str, Any] | None:
    """Kazami のアクセストークンから、今も有効なルームを引く。ルームが終わっていれば None。"""
    if not token:
        return None
    raw = get_store().get(f"guest-device-token:{devices._hash(token)}")
    if raw is None:
        return None
    data = json.loads(raw)
    room = _room_of_device(data["device_id"])
    if room is None or room["id"] != data["room_id"]:
        return None
    return {"name": DEVICE_NAME, "ayame_room_id": room["ayame_room_id"]}


# ── 利用規約への同意 ────────────────────────────────

TERMS_VERSION = "2026-10-19"
# 同意したことは 7 日だけ持つ（ゲストは「続きから使う」Cookie で、ルームの期限まで戻ってこられるため）。
# 規約の版が変わったら、もう一度同意してもらう
CONSENT_TTL_SECONDS = 7 * 24 * 60 * 60


def has_consented(viewer: Principal) -> bool:
    return get_store().get(f"guest-consent:{owner_of(viewer)}") == TERMS_VERSION


def consent(viewer: Principal, version: object) -> None:
    if str(version or "") != TERMS_VERSION:
        raise ValueError("利用規約が改められました。画面を開き直して、新しい内容を確認してください。")
    get_store().set(f"guest-consent:{owner_of(viewer)}", TERMS_VERSION, CONSENT_TTL_SECONDS)
