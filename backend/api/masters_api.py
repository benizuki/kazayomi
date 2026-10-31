"""マスター（ユーザー・グループ・サーバ・ルーム）の編集。

ユーザーとグループはアプリ全体の can_manage_users、サーバの編集はアプリ全体の can_manage_devices が要る。
ルームはそのグループでの can_manage_devices（グループ管理者もできる）。
変更はすべて監査ログに残す（「いつ誰にこの権限が付いたのか」に答えられるようにするため）。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.api_common import _request_json
from core.audit import record_operation
from core.auth import Viewer
from domain import app_settings, rooms, groups, servers, users

router = APIRouter(prefix="/api/masters")


def _audit(viewer, event: str, target: str, detail: str = "") -> None:
    record_operation(actor_email=viewer.email, event=event, target=target, detail=detail)


# ── ユーザー ──────────────────────────────────────

@router.get("/users")
def api_list_users(viewer: Viewer):
    viewer.require_global("can_manage_users")
    return users.list_users()


@router.post("/users")
async def api_create_user(request: Request, viewer: Viewer):
    viewer.require_global("can_manage_users")
    user = users.create_user(await _request_json(request))
    _audit(viewer, "user.create", user["email"], f"role={user['role']} groups={','.join(user['group_ids'])}")
    return JSONResponse(status_code=201, content=user)


@router.put("/users/{user_id}")
async def api_update_user(user_id: str, request: Request, viewer: Viewer):
    viewer.require_global("can_manage_users")
    before = users.get_user(user_id)
    user = users.update_user(user_id, await _request_json(request), actor_email=viewer.email)
    changes = [f"{key}: {before[key]} -> {user[key]}" for key in ("email", "role", "enabled", "group_ids") if before[key] != user[key]]
    _audit(viewer, "user.update", user["email"], "; ".join(changes))
    return user


@router.delete("/users/{user_id}")
def api_delete_user(user_id: str, viewer: Viewer):
    viewer.require_global("can_manage_users")
    removed = users.delete_user(user_id, actor_email=viewer.email)
    _audit(viewer, "user.delete", removed["email"])
    return {"ok": True}


# ── グループ ──────────────────────────────────────

@router.get("/groups")
def api_list_groups(viewer: Viewer):
    # 一覧はルームの編集（can_manage_devices）でも選択肢として使う。グループ管理者には自分のグループだけ
    if viewer.has_global("can_manage_users"):
        return groups.list_groups()
    viewer.require("can_manage_devices")
    ids = viewer.groups_with("can_manage_devices")
    return groups.list_groups(None if ids is None else sorted(ids))


@router.post("/groups")
async def api_create_group(request: Request, viewer: Viewer):
    viewer.require_global("can_manage_users")
    payload = await _request_json(request)
    # 上限を送らなければ「新しいグループの容量」にする
    if "quota_bytes" not in payload:
        payload["quota_bytes"] = app_settings.default_group_quota()
    group = groups.create_group(payload)
    _audit(viewer, "group.create", group["id"], f"{group['name']} quota={group['quota_bytes']}")
    return JSONResponse(status_code=201, content=group)


@router.put("/groups/{group_id}")
async def api_update_group(group_id: str, request: Request, viewer: Viewer):
    viewer.require_global("can_manage_users")
    before = groups.get_group(group_id)
    group = groups.update_group(group_id, await _request_json(request))
    _audit(viewer, "group.update", group_id,
           f"{group['name']} quota={before['quota_bytes']} -> {group['quota_bytes']}")
    return group


@router.delete("/groups/{group_id}")
def api_delete_group(group_id: str, viewer: Viewer):
    viewer.require_global("can_manage_users")
    groups.delete_group(group_id)
    _audit(viewer, "group.delete", group_id)
    return {"ok": True}


# ── アプリ全体の設定 ──────────────────────────────

@router.get("/settings")
def api_get_settings(viewer: Viewer):
    viewer.require_global("can_manage_users")
    return app_settings.get_all()


@router.put("/settings")
async def api_update_settings(request: Request, viewer: Viewer):
    viewer.require_global("can_manage_users")
    result = app_settings.update(await _request_json(request))
    _audit(viewer, "settings.update", "app",
           f"default_group_quota_bytes={result['default_group_quota_bytes']}")
    return result


# ── サーバ ────────────────────────────────────────

def _server_detail(server: dict) -> str:
    # API トークンは記録に残さない
    kind = f" kind={server['kind']}" + (f" key={server['turn_key_id']}" if server["kind"] == "cloudflare" else "")
    return f"{server['signaling_url']}{kind}{' （既定）' if server['is_default'] else ''}"


@router.get("/servers")
def api_list_servers(viewer: Viewer):
    # グループ管理者も、ルームのサーバを選ぶために一覧は見られる（編集はアプリ全体の権限が要る）
    viewer.require("can_manage_devices")
    return servers.list_servers()


@router.post("/servers")
async def api_create_server(request: Request, viewer: Viewer):
    viewer.require_global("can_manage_devices")
    server = servers.create_server(await _request_json(request))
    _audit(viewer, "server.create", server["name"], _server_detail(server))
    return JSONResponse(status_code=201, content=server)


@router.put("/servers/{server_id}")
async def api_update_server(server_id: str, request: Request, viewer: Viewer):
    viewer.require_global("can_manage_devices")
    server = servers.update_server(server_id, await _request_json(request))
    _audit(viewer, "server.update", server["name"], _server_detail(server))
    return server


@router.delete("/servers/{server_id}")
def api_delete_server(server_id: str, viewer: Viewer):
    viewer.require_global("can_manage_devices")
    server = servers.get_server(server_id)
    servers.delete_server(server_id)
    _audit(viewer, "server.delete", server["name"])
    return {"ok": True}


# ── ルーム ──────────────────────────────────────

@router.get("/rooms")
def api_list_rooms(viewer: Viewer):
    viewer.require("can_manage_devices")
    return rooms.list_rooms(viewer.scoped("can_manage_devices"))


@router.post("/rooms")
async def api_create_room(request: Request, viewer: Viewer):
    payload = await _request_json(request)
    viewer.require_in(str(payload.get("group_id") or ""), "can_manage_devices")
    room = rooms.create_room(payload)
    _audit(viewer, "room.create", room["name"], f"room={room['ayame_room_id']} group={room['group_id']}")
    return JSONResponse(status_code=201, content=room)


@router.put("/rooms/{room_id}")
async def api_update_room(room_id: str, request: Request, viewer: Viewer):
    payload = await _request_json(request)
    current = rooms.get_room(room_id)
    viewer.require_in(current["group_id"], "can_manage_devices")
    # 別のグループへ移すときは、移す先でも管理できること
    viewer.require_in(str(payload.get("group_id") or current["group_id"]), "can_manage_devices")
    room = rooms.update_room(room_id, payload)
    _audit(viewer, "room.update", room["name"], f"room={room['ayame_room_id']} group={room['group_id']}")
    return room


@router.delete("/rooms/{room_id}")
def api_delete_room(room_id: str, viewer: Viewer):
    room = rooms.get_room(room_id)
    viewer.require_in(room["group_id"], "can_manage_devices")
    rooms.delete_room(room_id)
    _audit(viewer, "room.delete", room["name"], f"room={room['ayame_room_id']}")
    return {"ok": True}
