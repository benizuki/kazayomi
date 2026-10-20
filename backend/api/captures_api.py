"""撮像トークンの発行と、Kazami からのアップロード。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from config.settings import get_settings
from core.api_common import _request_json, read_upload
from core.auth import Viewer
from domain import captures

router = APIRouter(prefix="/api/captures")


@router.post("")
async def api_create_capture(request: Request, viewer: Viewer):
    """ログイン中のユーザーが、見られるルームにだけ撮像を頼める。"""
    payload = await _request_json(request)
    ttl = get_settings().capture_token_ttl_seconds
    return JSONResponse(status_code=201, content=captures.create_capture(payload, viewer=viewer, ttl_seconds=ttl))


@router.get("/{capture_id}")
def api_capture_status(capture_id: str, viewer: Viewer):  # noqa: ARG001 - ログインの確認だけ
    return captures.capture_status(capture_id)


@router.post("/{capture_id}/image")
async def api_upload_capture(
    capture_id: str,
    request: Request,
    image: UploadFile = File(...),
    capturedAt: str | None = Form(default=None),  # noqa: N803 - Kazami 側のフィールド名に合わせる
):
    """Kazami からのアップロード。Authorization: Bearer <撮像トークン> が必要。

    ログインは要らない（Kazami はログインしない）。撮像を頼んだ人の権限は、トークンの発行時に確かめてある。
    """
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    data = await read_upload(image)
    record = captures.accept_upload(
        capture_id, token, data, captured_at=capturedAt, source_name=image.filename or ""
    )
    return JSONResponse(status_code=201, content=record)
