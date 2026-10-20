"""グループのメンバーと招待。

- グループを作れるのはアプリの管理者だけ（マスター › グループ）。誰でも作れると、誰でもメールアドレスを
  登録できてしまうため。最初のグループ管理者は、アプリの管理者がマスター › メンバーで招待する
- グループ管理者は、メールアドレスを指定して招待する。本人がそのアドレスの Google アカウントで
  サインインすると、参加するかを選べる。URL を知っているだけの別人は入れない
- グループには、いつも 1 人以上のグループ管理者を残す
- グループ管理者は、自分のグループを中身ごと消せる（ルーム・デバイス・画像・アルバム・招待と、
  このグループにしか入っていないメンバーのアカウント）
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from core.db import connect
from domain import groups, images, users
from domain.access import GROUP_ROLES
from domain.common import NotFoundError, new_id, now_local, require_text, to_iso

INVITATION_DAYS = 14
_EMAIL_PATTERN = users._EMAIL_PATTERN


def _require_group_role(value: object) -> str:
    role = str(value or "viewer")
    if role not in GROUP_ROLES:
        raise ValueError("役割はグループ管理者・編集者・閲覧者のいずれかです。")
    return role


# グループを消すときに、アカウントごと消す人: このグループにしか入っておらず、全体のロールが閲覧者（user）の人。
# ほかのグループにも入っている人は、そちらで使い続けるので残す。
# 全体のロールが user 以外の人は、アプリの管理者が役割を付けた人なので残す（アプリの管理者が判断する）
_ONLY_HERE = """
SELECT u.id, u.email FROM users u JOIN user_groups ug ON ug.user_id = u.id
WHERE ug.group_id = ? AND u.role = 'user'
  AND NOT EXISTS (SELECT 1 FROM user_groups other WHERE other.user_id = u.id AND other.group_id != ug.group_id)
"""


def group_contents(group_id: str) -> dict[str, int]:
    """消す前に見せる、グループの中身の数。"""
    groups.get_group(group_id)
    with connect() as conn:
        def count(sql: str) -> int:
            return conn.execute(sql, (group_id,)).fetchone()[0]
        return {
            "rooms": count("SELECT COUNT(*) FROM rooms WHERE group_id = ?"),
            "devices": count("SELECT COUNT(*) FROM devices WHERE room_id IN (SELECT id FROM rooms WHERE group_id = ?)"),
            "images": count("SELECT COUNT(*) FROM images WHERE group_id = ?"),
            "albums": count("SELECT COUNT(*) FROM albums WHERE group_id = ?"),
            "members": count("SELECT COUNT(*) FROM user_groups WHERE group_id = ?"),
            "users_deleted": count(f"SELECT COUNT(*) FROM ({_ONLY_HERE})"),
            "invitations": count("SELECT COUNT(*) FROM group_invitations WHERE group_id = ?"),
        }


def delete_group_with_contents(group_id: str, confirm_name: object) -> dict[str, Any]:
    """グループを中身ごと消す。元に戻せないので、グループ名を打ち込んで確かめる。

    - デバイスも消す（ルームのない端末はグループ管理者から見えなくなり、残しても誰も扱えないため）。
      消えた端末のアクセストークンは使えなくなる
    - このグループにしか入っていないメンバーは、アカウントごと消す（_ONLY_HERE）。ほかの人はグループから外すだけ
    - DB は 1 つのトランザクションで消し、画像のファイルはそのあとで消す
    """
    if group_id == "default":
        raise ValueError("既定のグループは削除できません。")
    group = groups.get_group(group_id)
    if str(confirm_name or "").strip() != group["name"]:
        raise ValueError("確認のため、グループ名を正確に入力してください。")
    contents = group_contents(group_id)
    with connect() as conn:
        files = [(r["id"], r["path"]) for r in conn.execute("SELECT id, path FROM images WHERE group_id = ?", (group_id,))]
        doomed = [(r["id"], r["email"]) for r in conn.execute(_ONLY_HERE, (group_id,))]
        conn.execute("DELETE FROM devices WHERE room_id IN (SELECT id FROM rooms WHERE group_id = ?)", (group_id,))
        conn.execute("DELETE FROM albums WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM images WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM rooms WHERE group_id = ?", (group_id,))
        # 所属と招待は外部キーの CASCADE で消える
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.executemany("DELETE FROM users WHERE id = ?", [(user_id,) for user_id, _ in doomed])
    images.delete_files(files)
    return {"group": group, "deleted": contents, "deleted_users": sorted(email for _, email in doomed)}


# ── メンバー ──────────────────────────────────────

def list_members(group_id: str) -> list[dict[str, Any]]:
    groups.get_group(group_id)
    with connect() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.name, u.role AS global_role, u.enabled, u.last_login_at, ug.role
               FROM user_groups ug JOIN users u ON u.id = ug.user_id
               WHERE ug.group_id = ? ORDER BY CASE ug.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END, u.email""",
            (group_id,),
        ).fetchall()
    return [{
        "user_id": r["id"], "email": r["email"], "name": r["name"], "role": r["role"],
        "global_role": r["global_role"], "enabled": bool(r["enabled"]), "last_login_at": r["last_login_at"],
    } for r in rows]


def _member_role(conn: sqlite3.Connection, user_id: str, group_id: str) -> str | None:
    row = conn.execute("SELECT role FROM user_groups WHERE user_id = ? AND group_id = ?", (user_id, group_id)).fetchone()
    return row[0] if row else None


def _owner_count(conn: sqlite3.Connection, group_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM user_groups ug JOIN users u ON u.id = ug.user_id"
                        " WHERE ug.group_id = ? AND ug.role = 'owner' AND u.enabled = 1", (group_id,)).fetchone()[0]


def _add_member(user_id: str, group_id: str, role: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO user_groups (user_id, group_id, role) VALUES (?, ?, ?)"
            " ON CONFLICT (user_id, group_id) DO UPDATE SET role = excluded.role",
            (user_id, group_id, role),
        )


def update_member(group_id: str, user_id: str, role: object) -> dict[str, Any]:
    role = _require_group_role(role)
    with connect() as conn:
        current = _member_role(conn, user_id, group_id)
        if current is None:
            raise NotFoundError("このグループのメンバーではありません。")
        if current == "owner" and role != "owner" and _owner_count(conn, group_id) <= 1:
            raise ValueError("グループ管理者がいなくなるため変更できません。先に別の人をグループ管理者にしてください。")
        conn.execute("UPDATE user_groups SET role = ? WHERE user_id = ? AND group_id = ?", (role, user_id, group_id))
    return next(m for m in list_members(group_id) if m["user_id"] == user_id)


def remove_member(group_id: str, user_id: str) -> dict[str, Any]:
    member = next((m for m in list_members(group_id) if m["user_id"] == user_id), None)
    if member is None:
        raise NotFoundError("このグループのメンバーではありません。")
    with connect() as conn:
        if member["role"] == "owner" and _owner_count(conn, group_id) <= 1:
            raise ValueError("最後のグループ管理者は外せません。先に別の人をグループ管理者にしてください。")
        conn.execute("DELETE FROM user_groups WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    return member


# ── 招待 ─────────────────────────────────────────

def _invitation(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        "email": row["email"],
        "role": row["role"],
        "invited_by": row["invited_by"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "expired": row["expires_at"] < to_iso(now_local()),
    }


_INVITATION_SELECT = """
SELECT i.*, g.name AS group_name FROM group_invitations i JOIN groups g ON g.id = i.group_id
"""


def list_invitations(group_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(_INVITATION_SELECT + " WHERE i.group_id = ? ORDER BY i.created_at DESC", (group_id,)).fetchall()
    return [_invitation(r) for r in rows]


def invitations_for(email: str) -> list[dict[str, Any]]:
    """本人に届いている、期限内の招待。"""
    with connect() as conn:
        rows = conn.execute(_INVITATION_SELECT + " WHERE i.email = ? AND i.expires_at >= ? ORDER BY i.created_at",
                            (users.normalize_email(email), to_iso(now_local()))).fetchall()
    return [_invitation(r) for r in rows]


def invite(group_id: str, email: object, role: object, *, invited_by: str) -> dict[str, Any]:
    """招待を作る。同じ人をもう一度招待すると、役割と期限を新しくする。"""
    groups.get_group(group_id)
    address = users.normalize_email(email)
    if not _EMAIL_PATTERN.match(address):
        raise ValueError("メールアドレスの形式が正しくありません。")
    role = _require_group_role(role)
    existing = users.find_by_email(address)
    if existing is not None and group_id in existing["group_ids"]:
        raise ValueError(f"{address} はもうこのグループのメンバーです。")
    now = now_local()
    with connect() as conn:
        conn.execute(
            """INSERT INTO group_invitations (id, group_id, email, role, invited_by, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (group_id, email) DO UPDATE SET
                 role = excluded.role, invited_by = excluded.invited_by,
                 created_at = excluded.created_at, expires_at = excluded.expires_at""",
            (new_id(), group_id, address, role, users.normalize_email(invited_by),
             to_iso(now), to_iso(now + timedelta(days=INVITATION_DAYS))),
        )
        row = conn.execute(_INVITATION_SELECT + " WHERE i.group_id = ? AND i.email = ?", (group_id, address)).fetchone()
    return _invitation(row)


def get_invitation(invitation_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(_INVITATION_SELECT + " WHERE i.id = ?", (invitation_id,)).fetchone()
    if row is None:
        raise NotFoundError("招待が見つかりません。取り消されたかもしれません。")
    return _invitation(row)


def cancel_invitation(group_id: str, invitation_id: str) -> dict[str, Any]:
    invitation = get_invitation(invitation_id)
    if invitation["group_id"] != group_id:
        raise NotFoundError("招待が見つかりません。取り消されたかもしれません。")
    _delete_invitation(invitation_id)
    return invitation


def _delete_invitation(invitation_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM group_invitations WHERE id = ?", (invitation_id,))


def _own_invitation(invitation_id: str, email: str) -> dict[str, Any]:
    """本人あての、期限内の招待。ほかの人あての招待は「見つからない」と同じに扱う。"""
    invitation = get_invitation(invitation_id)
    if invitation["email"] != users.normalize_email(email):
        raise NotFoundError("招待が見つかりません。取り消されたかもしれません。")
    if invitation["expired"]:
        raise ValueError("招待の期限が切れています。グループの管理者に招待し直してもらってください。")
    return invitation


def accept_invitation(invitation_id: str, email: str, *, user_name: str = "") -> dict[str, Any]:
    """招待を受けて参加する。まだユーザーでなければユーザーも作る。"""
    invitation = _own_invitation(invitation_id, email)
    existing = users.find_by_email(email)
    if existing is not None and not existing["enabled"]:
        raise ValueError("このアカウントは利用が止められています。管理者に確認してください。")
    if existing is None:
        user = users.create_user({"email": email, "name": user_name or str(email).split("@")[0], "role": "user",
                                  "group_ids": [invitation["group_id"]]},
                                 group_roles={invitation["group_id"]: invitation["role"]})
    else:
        if invitation["group_id"] not in existing["group_ids"]:
            _add_member(existing["id"], invitation["group_id"], invitation["role"])
        user = users.get_user(existing["id"])
    _delete_invitation(invitation_id)
    return {"invitation": invitation, "user": user, "user_created": existing is None}


def decline_invitation(invitation_id: str, email: str) -> dict[str, Any]:
    invitation = get_invitation(invitation_id)
    if invitation["email"] != users.normalize_email(email):
        raise NotFoundError("招待が見つかりません。取り消されたかもしれません。")
    _delete_invitation(invitation_id)
    return invitation
