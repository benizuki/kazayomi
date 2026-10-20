"""ライブラリ（蓄積した画像）。見られるのは所属グループの画像だけ。"""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from core.api_common import _request_json, zip_response
from core.audit import record_operation
from core.auth import Viewer
from domain import images
from domain.common import normalize_tags

router = APIRouter(prefix="/api/images")


@router.get("")
def api_list_images(
    viewer: Viewer,
    room_id: str | None = None,
    room_name: str | None = None,
    group_id: str | None = None,
    date_from: str | None = Query(default=None, pattern=r"^\d{8}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{8}$"),
    tags: str | None = None,
    favorite: bool | None = None,
    limit: int = 500,
    offset: int = 0,
):
    group_ids = viewer.visible_group_ids()
    if group_id:
        viewer.require_group(group_id)
        group_ids = [group_id]
    flt = images.ImageFilter(
        room_id=room_id or None,
        room_name=room_name,
        group_ids=group_ids,
        date_from=date_from,
        date_to=date_to,
        tags=normalize_tags(tags, limit=None) or None,
        favorite=favorite,
    )
    return images.list_images(flt, limit=limit, offset=offset)


@router.get("/summary")
def api_summary(
    viewer: Viewer,
    date_from: str | None = Query(default=None, pattern=r"^\d{8}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{8}$"),
):
    return images.summary(date_from, date_to, viewer.visible_group_ids())


@router.get("/tags")
def api_tags(viewer: Viewer):
    return images.tag_counts(viewer.visible_group_ids())


@router.post("/tags/batch")
async def api_batch_tags(request: Request, viewer: Viewer):
    viewer.require("can_edit")
    payload = await _request_json(request)
    # 編集できないグループの画像は飛ばす
    updated = images.batch_update_tags(payload.get("ids"), payload.get("tags"), str(payload.get("mode", "add")),
                                       viewer.scoped("can_edit"))
    return {"updated": updated}


@router.post("/delete")
async def api_delete_images(request: Request, viewer: Viewer):
    viewer.require("can_edit")
    payload = await _request_json(request)
    deleted = images.delete_images(payload.get("ids"), viewer.scoped("can_edit"))
    record_operation(actor_email=viewer.email, event="image.delete", target=f"{deleted} images",
                     category="operation", detail=",".join(str(i) for i in (payload.get("ids") or [])[:50]))
    return {"deleted": deleted}


@router.post("/album-usage")
async def api_album_usage(request: Request, viewer: Viewer):
    payload = await _request_json(request)
    return {"count": images.count_album_usage(payload.get("ids"), viewer)}


@router.post("/zip")
async def api_zip(request: Request, viewer: Viewer) -> StreamingResponse:
    payload = await _request_json(request)
    return zip_response(images.zip_images(payload.get("ids"), viewer), "kazayomi-images.zip")


@router.get("/{image_id}")
def api_get_image(image_id: str, viewer: Viewer):
    return images.get_image(image_id, viewer)


@router.patch("/{image_id}")
async def api_update_image(image_id: str, request: Request, viewer: Viewer):
    payload = await _request_json(request)
    # お気に入りは閲覧だけの人も付けられる。タグ・メモ・図形は編集権限が要る
    if set(payload) - {"favorite"}:
        viewer.require_in(images.get_image(image_id, viewer)["group_id"], "can_edit")
    return images.update_image(image_id, payload, viewer)


@router.get("/{image_id}/file")
def api_image_file(image_id: str, viewer: Viewer, download: bool = False):
    """画像本体。rustfs から少しずつ読んで返す（ブラウザから rustfs には直接つながない）。"""
    chunks, size, content_type = images.open_image(image_id, viewer)
    headers = {"Cache-Control": "private, max-age=86400"}
    if size:
        headers["Content-Length"] = str(size)
    if download:
        record = images.get_image(image_id, viewer)
        name = images.download_name(record, images.image_key(image_id, viewer))
        headers["Content-Disposition"] = f"attachment; filename=\"download{PurePosixPath(name).suffix}\"; filename*=UTF-8''{quote(name)}"
    return StreamingResponse(chunks, media_type=content_type, headers=headers)


@router.get("/{image_id}/thumb")
def api_image_thumb(image_id: str, viewer: Viewer):
    return Response(
        images.read_thumbnail(image_id, viewer),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )
