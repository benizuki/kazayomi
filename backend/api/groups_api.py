"""グループの管理者が使う、メンバーと招待の API と、自分あての招待を受ける API。

メンバーの管理は can_manage_members をそのグループで持つ人（グループ管理者と、アプリの管理者）だけ。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.api_common import _request_json
from core.audit import record_operation
from core.auth import Viewer
from domain import groups, memberships

router = APIRouter()


def _audit(viewer, event: str, target: str, detail: str = "") -> None:
    record_operation(actor_email=viewer.email, event=event, target=target, detail=detail)


@router.get("/api/groups/managed")
def api_managed_groups(viewer: Viewer):
    """メンバーを管理できるグループ。"""
    viewer.require("can_manage_members")
    ids = viewer.groups_with("can_manage_members")
    return groups.list_groups(None if ids is None else sorted(ids))


@router.get("/api/groups/{group_id}/contents")
def api_group_contents(group_id: str, viewer: Viewer):
    """削除の確認に出す、グループの中身の数。"""
    viewer.require_in(group_id, "can_manage_members")
    return memberships.group_contents(group_id)


@router.post("/api/groups/{group_id}/delete")
async def api_delete_group(group_id: str, request: Request, viewer: Viewer):
    """グループを中身ごと消す。グループ管理者（とアプリの管理者）だけ。

    本文に confirm_name（グループ名）が要るので、DELETE ではなく POST で受ける。
    """
    viewer.require_in(group_id, "can_manage_members")
    result = memberships.delete_group_with_contents(group_id, (await _request_json(request)).get("confirm_name"))
    d = result["deleted"]
    _audit(viewer, "group.delete", group_id,
           f"{result['group']['name']}（中身ごと: ルーム {d['rooms']}・デバイス {d['devices']}・画像 {d['images']}・"
           f"アルバム {d['albums']}・メンバー {d['members']}・招待 {d['invitations']}）")
    # アカウントごと消した人は、1 人ずつ残す（「いつ誰のアカウントが消えたか」に答えられるように）
    for email in result["deleted_users"]:
        _audit(viewer, "user.delete", email, f"グループ {group_id} の削除にともなう")
    return {"ok": True, "deleted": d, "self_deleted": viewer.email in result["deleted_users"]}


@router.get("/api/groups/{group_id}/members")
def api_list_members(group_id: str, viewer: Viewer):
    viewer.require_in(group_id, "can_manage_members")
    return {"members": memberships.list_members(group_id), "invitations": memberships.list_invitations(group_id)}


@router.put("/api/groups/{group_id}/members/{user_id}")
async def api_update_member(group_id: str, user_id: str, request: Request, viewer: Viewer):
    viewer.require_in(group_id, "can_manage_members")
    member = memberships.update_member(group_id, user_id, (await _request_json(request)).get("role"))
    _audit(viewer, "member.update", member["email"], f"group={group_id} role={member['role']}")
    return member


@router.delete("/api/groups/{group_id}/members/{user_id}")
def api_remove_member(group_id: str, user_id: str, viewer: Viewer):
    viewer.require_in(group_id, "can_manage_members")
    member = memberships.remove_member(group_id, user_id)
    _audit(viewer, "member.remove", member["email"], f"group={group_id}")
    return {"ok": True}


@router.post("/api/groups/{group_id}/invitations")
async def api_invite(group_id: str, request: Request, viewer: Viewer):
    viewer.require_in(group_id, "can_manage_members")
    payload = await _request_json(request)
    invitation = memberships.invite(group_id, payload.get("email"), payload.get("role"), invited_by=viewer.email)
    _audit(viewer, "invitation.create", invitation["email"], f"group={group_id} role={invitation['role']}")
    return JSONResponse(status_code=201, content=invitation)


@router.delete("/api/groups/{group_id}/invitations/{invitation_id}")
def api_cancel_invitation(group_id: str, invitation_id: str, viewer: Viewer):
    viewer.require_in(group_id, "can_manage_members")
    invitation = memberships.cancel_invitation(group_id, invitation_id)
    _audit(viewer, "invitation.cancel", invitation["email"], f"group={group_id}")
    return {"ok": True}


# ── 自分あての招待（ログイン済みの人）─────────────────

@router.post("/api/invitations/{invitation_id}/accept")
def api_accept_invitation(invitation_id: str, viewer: Viewer):
    result = memberships.accept_invitation(invitation_id, viewer.email)
    invitation = result["invitation"]
    record_operation(actor_email=viewer.email, event="invitation.accept", target=invitation["group_id"],
                     detail=f"role={invitation['role']} invited_by={invitation['invited_by']}")
    return {"ok": True, "group_id": invitation["group_id"], "group_name": invitation["group_name"]}


@router.delete("/api/invitations/{invitation_id}")
def api_decline_invitation(invitation_id: str, viewer: Viewer):
    invitation = memberships.decline_invitation(invitation_id, viewer.email)
    record_operation(actor_email=viewer.email, event="invitation.decline", target=invitation["group_id"])
    return {"ok": True}
