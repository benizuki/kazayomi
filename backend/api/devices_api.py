"""デバイス（Kazami 端末）。

- /api/masters/devices … 管理画面。デバイスのルームのグループで can_manage_devices が要る
                         （ルームのないデバイスは、アプリ全体の can_manage_devices を持つ人だけ）
- /api/devices/…       … Kazami が呼ぶ。ログインは要らず、QR の登録トークンと端末の署名
                         （撮像ボタンの画像はデバイスのアクセストークン）で確かめる
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from config.settings import get_settings
from core.api_common import _request_json, read_upload
from core.audit import record_operation
from core.auth import Viewer, client_ip
from domain import captures, devices, rooms

router = APIRouter()


def _audit(viewer, event: str, target: str, detail: str = "") -> None:
    record_operation(actor_email=viewer.email, event=event, target=target, detail=detail)


def _room_group(room_id: object) -> str | None:
    return rooms.get_room(str(room_id))["group_id"] if room_id else None


def _manageable_device(row_id: str, viewer) -> dict:
    device = devices.get_device(row_id)
    viewer.require_in(device["group_id"] or None, "can_manage_devices")
    return device


# ── 管理画面 ──────────────────────────────────────

@router.get("/api/masters/devices")
def api_list_devices(viewer: Viewer):
    viewer.require("can_manage_devices")
    return [d for d in devices.list_devices() if viewer.can_in(d["group_id"] or None, "can_manage_devices")]


@router.post("/api/masters/devices")
async def api_create_device(request: Request, viewer: Viewer):
    payload = await _request_json(request)
    viewer.require_in(_room_group(payload.get("room_id")), "can_manage_devices")
    device = devices.create_device(payload)
    _audit(viewer, "device.create", device["name"], f"room={device['room_name']}")
    return JSONResponse(status_code=201, content=device)


@router.put("/api/masters/devices/{row_id}")
async def api_update_device(row_id: str, request: Request, viewer: Viewer):
    payload = await _request_json(request)
    _manageable_device(row_id, viewer)
    viewer.require_in(_room_group(payload.get("room_id")), "can_manage_devices")
    device = devices.update_device(row_id, payload)
    _audit(viewer, "device.update", device["name"], f"room={device['room_name']}")
    return device


@router.delete("/api/masters/devices/{row_id}")
def api_delete_device(row_id: str, viewer: Viewer):
    _manageable_device(row_id, viewer)
    device = devices.delete_device(row_id)
    _audit(viewer, "device.delete", device["name"], f"device_id={device['device_id']}")
    return {"ok": True}


@router.post("/api/masters/devices/{row_id}/enrollment")
def api_issue_enrollment(row_id: str, request: Request, viewer: Viewer):
    """登録 QR の中身を返す。api は Kazami から届く kazayomi の URL。"""
    _manageable_device(row_id, viewer)
    issued = devices.issue_enrollment(row_id)
    _audit(viewer, "device.enrollment.issue", issued["name"])
    return {**issued, "suggested_api_url": _public_base_url(request)}


@router.delete("/api/masters/devices/{row_id}/enrollment")
def api_clear_enrollment(row_id: str, viewer: Viewer):
    _manageable_device(row_id, viewer)
    device = devices.clear_enrollment(row_id)
    _audit(viewer, "device.enrollment.clear", device["name"])
    return device


def _public_base_url(request: Request) -> str:
    """Kazami から見た kazayomi の URL の候補。設定があればそれ、無ければ今のリクエストから組み立てる。"""
    configured = get_settings().public_base_url
    if configured:
        return configured.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


# ── Kazami が呼ぶ ─────────────────────────────────

@router.post("/api/devices/enroll")
async def api_enroll(request: Request):
    payload = await _request_json(request)
    result = devices.enroll(payload, ip=client_ip(request))
    record_operation(actor_email="", event="device.enroll", target=result["name"],
                     detail=f"device_id={result['device_id']} ip={client_ip(request)}")
    return result


@router.post("/api/devices/challenge")
async def api_challenge(request: Request):
    payload = await _request_json(request)
    return devices.issue_challenge(payload)


@router.post("/api/devices/token")
async def api_token(request: Request):
    settings = get_settings()
    payload = await _request_json(request)
    return devices.issue_token(
        payload,
        ttl_seconds=settings.device_token_ttl_seconds,
        default_signaling_url=rooms.default_signaling_url(),
        ip=client_ip(request),
    )


@router.post("/api/devices/images")
async def api_device_image(
    request: Request,
    image: UploadFile = File(...),
    capturedAt: str | None = Form(default=None),  # noqa: N803 - Kazami 側のフィールド名に合わせる
):
    """Kazami の撮像ボタンで撮った画像。Authorization: Bearer <デバイスのアクセストークン> が必要。"""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    data = await read_upload(image)
    record = captures.accept_device_upload(token, data, captured_at=capturedAt, source_name=image.filename or "")
    return JSONResponse(status_code=201, content=record)
