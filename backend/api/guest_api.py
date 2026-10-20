"""ゲスト（ユーザーのマスターにいない人）の API。一時的なルームと、利用規約への同意。

ルームを使う前に、利用規約とプライバシーポリシーへの同意を求める（同意は期限付きで Valkey に持つだけ）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket

from api.devices_api import _public_base_url
from api.signaling_api import _CLOSE_NOT_FOUND, _CLOSE_UNAUTHORIZED, _origin_allowed, relay
from core.api_common import _request_json
from core.auth import Viewer, current_principal, ensure_resume_code
from domain import guest_rooms, room_access, rooms
from domain.common import NotFoundError

router = APIRouter(prefix="/api/guest")

_CLOSE_CONSENT_REQUIRED = 4451


def _require_consent(viewer) -> None:
    if not guest_rooms.has_consented(viewer):
        raise HTTPException(status_code=403, detail="利用規約とプライバシーポリシーへの同意が必要です。画面を開き直してください。")


@router.post("/consent")
async def api_consent(request: Request, viewer: Viewer):
    guest_rooms.consent(viewer, (await _request_json(request)).get("version"))
    return {"ok": True, "version": guest_rooms.TERMS_VERSION}


@router.get("/room")
def api_room(request: Request, viewer: Viewer):
    """自分の一時的なルーム。なければ作る。開くたびに期限が延びる。

    再開コード（ログアウトしたあとや別のブラウザから戻るためのもの）も返す。本人にだけ見せる。
    """
    _require_consent(viewer)
    return {**guest_rooms.get_or_create(viewer), "resume_code": ensure_resume_code(request, viewer)}


@router.delete("/room")
def api_end_room(viewer: Viewer):
    _require_consent(viewer)
    guest_rooms.end(viewer)
    return {"ok": True}


@router.post("/room/enrollment")
def api_enrollment(request: Request, viewer: Viewer):
    """Kazami に読ませる登録 QR の中身（10 分・1 回限り）。"""
    _require_consent(viewer)
    issued = guest_rooms.issue_enrollment(viewer)
    return {**issued, "api": _public_base_url(request)}


@router.post("/room/ticket")
def api_ticket(viewer: Viewer):
    _require_consent(viewer)
    return room_access.issue_guest_ticket(viewer)


@router.websocket("/room/signaling")
async def ws_signaling(websocket: WebSocket):
    if not _origin_allowed(websocket):
        await websocket.close(code=4403)
        return
    viewer = current_principal(websocket)
    if viewer is None:
        await websocket.close(code=_CLOSE_UNAUTHORIZED)
        return
    if not guest_rooms.has_consented(viewer):
        await websocket.close(code=_CLOSE_CONSENT_REQUIRED)
        return
    try:
        guest_rooms.require_room(viewer)
    except NotFoundError:
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return
    await relay(websocket, rooms.default_signaling_url())
