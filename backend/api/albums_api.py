"""アルバム。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.api_common import _request_json, zip_response
from core.audit import record_operation
from core.auth import Viewer
from domain import albums

router = APIRouter(prefix="/api/albums")


# 閲覧（一覧・中身・書き出し）は can_view、変更はアルバムのグループでの can_edit が要る。どれも所属グループのアルバムだけ


def _editable(album_id: str, viewer):
    """変えてよいアルバムか確かめ、編集できるグループだけが見える Principal を返す。"""
    album = albums.get_album(album_id, viewer)
    viewer.require_in(album["group_id"], "can_edit")
    return viewer.scoped("can_edit")


@router.get("")
def api_list_albums(viewer: Viewer):
    return albums.list_albums(viewer)


@router.post("")
async def api_create_album(request: Request, viewer: Viewer):
    viewer.require("can_edit")
    # 作れるのは、編集できるグループのアルバムだけ
    return JSONResponse(status_code=201, content=albums.create_album(await _request_json(request), viewer.scoped("can_edit")))


@router.get("/{album_id}")
def api_get_album(album_id: str, viewer: Viewer):
    return albums.get_album(album_id, viewer)


@router.patch("/{album_id}")
async def api_update_album(album_id: str, request: Request, viewer: Viewer):
    return albums.update_album(album_id, await _request_json(request), _editable(album_id, viewer))


@router.delete("/{album_id}")
def api_delete_album(album_id: str, viewer: Viewer):
    editor = _editable(album_id, viewer)
    album = albums.get_album(album_id, viewer)
    albums.delete_album(album_id, editor)
    record_operation(actor_email=viewer.email, event="album.delete", target=album["name"], category="operation",
                     detail=f"items={album['item_count']}")
    return {"ok": True}


@router.get("/{album_id}/items")
def api_list_items(album_id: str, viewer: Viewer):
    return albums.list_items(album_id, viewer)


@router.post("/{album_id}/items")
async def api_add_items(album_id: str, request: Request, viewer: Viewer):
    editor = _editable(album_id, viewer)
    payload = await _request_json(request)
    return albums.add_items(album_id, payload.get("ids"), editor)


@router.post("/{album_id}/items/remove")
async def api_remove_items(album_id: str, request: Request, viewer: Viewer):
    editor = _editable(album_id, viewer)
    payload = await _request_json(request)
    return {"removed": albums.remove_items(album_id, payload.get("ids"), editor)}


@router.get("/{album_id}/export")
def api_export(album_id: str, viewer: Viewer):
    filename, buffer = albums.export_zip(album_id, viewer)
    return zip_response(buffer, filename)
