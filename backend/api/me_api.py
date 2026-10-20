"""ログイン中のユーザーと、閲覧用のルーム一覧・監査ログ。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from core.audit import list_auth_audit_logs
from core.auth import Viewer, auth_mode, session_picture
from domain import groups, guest_rooms, memberships, rooms

router = APIRouter()


@router.get("/api/me")
def api_me(request: Request, viewer: Viewer):
    """画面は起動時にこれを待ってから描く。先に描くと、権限のないボタンが一瞬見えてしまう。"""
    if viewer.is_guest:
        return _guest_me(viewer)
    return {
        "guest": False,
        "user": {"email": viewer.email, "name": viewer.name, "picture": session_picture(request)},
        "role": viewer.role,
        # どれかのグループで持っている権限（画面の出し分け用）と、全体のロールの権限
        "permissions": viewer.effective_permissions(),
        "global_permissions": viewer.permissions,
        # 所属グループでの役割（owner / editor / viewer）
        "group_roles": dict(viewer.group_roles),
        # 画面の選択肢（取り込み先・アルバムのグループ）に使う。admin は全グループ
        "groups": [{"id": g["id"], "name": g["name"]} for g in groups.list_groups(viewer.visible_group_ids())],
        "all_groups": viewer.all_groups,
        # "dev-bypass" のとき、画面は常時バナーを出す
        "auth_mode": auth_mode(),
        # 自分あての、まだ受けていない招待
        "invitations": [
            {"id": i["id"], "group_name": i["group_name"], "role": i["role"], "expires_at": i["expires_at"]}
            for i in memberships.invitations_for(viewer.email)
        ],
    }


def _guest_me(viewer) -> dict:
    """ゲスト。名前もメールアドレスも持っていないので、出せるものだけ返す。使えるのは一時的なルームだけ。"""
    none = {key: False for key in viewer.permissions}
    return {
        "guest": True,
        "user": {"email": "", "name": viewer.name, "picture": ""},
        "role": viewer.role,
        "permissions": none,
        "global_permissions": none,
        "group_roles": {},
        "groups": [],
        "all_groups": False,
        "auth_mode": auth_mode(),
        "invitations": [],
        "consent": {"required": not guest_rooms.has_consented(viewer), "version": guest_rooms.TERMS_VERSION},
    }


@router.get("/api/rooms")
def api_list_visible_rooms(viewer: Viewer):
    """自分が見られるグループのルーム。"""
    return rooms.list_rooms(viewer)


@router.get("/api/rooms/{room_id}")
def api_get_room(room_id: str, viewer: Viewer):
    return rooms.get_room(room_id, viewer)


@router.get("/api/audit-logs")
def api_audit_logs(viewer: Viewer, limit: int = 500):
    # 監査ログは生のメールアドレスを含むので、管理者だけに見せる
    viewer.require("can_manage_users")
    return list_auth_audit_logs(limit)
