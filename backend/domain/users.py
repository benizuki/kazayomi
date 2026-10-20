"""ユーザー。Google でログインできても、ここに登録されて有効でなければ使えない。

Google アカウントは誰でも持てるので、署名の検証を通っただけでは通さない。
ロールと所属グループはリクエストのたびに読み直す（セッションには持たない）。
無効化や権限の変更が、次の操作からすぐ効くようにするため。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from core.db import connect
from domain import groups
from domain.access import ROLES, Principal, permissions_for_role
from domain.common import NotFoundError, new_id, now_local, require_text, to_iso

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def _group_roles(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT group_id, role FROM user_groups WHERE user_id = ? ORDER BY group_id", (user_id,))}


def _record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    group_roles = _group_roles(conn, row["id"])
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "group_ids": list(group_roles),
        "group_roles": group_roles,
        "permissions": permissions_for_role(row["role"]),
        "last_login_at": row["last_login_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY email").fetchall()
        return [_record(conn, row) for row in rows]


def get_user(user_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError("ユーザーが見つかりません。")
        return _record(conn, row)


def find_by_email(email: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        return _record(conn, row) if row else None


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    email = normalize_email(payload.get("email"))
    if not _EMAIL_PATTERN.match(email):
        raise ValueError("メールアドレスの形式が正しくありません。")
    role = str(payload.get("role") or "user")
    if role not in ROLES:
        raise ValueError("ロールは admin・device_admin・power・user のいずれかです。")
    group_ids = payload.get("group_ids") or []
    if not isinstance(group_ids, list):
        raise ValueError("所属グループは一覧で指定してください。")
    group_ids = sorted({str(g) for g in group_ids})
    unknown = [g for g in group_ids if not groups.exists(g)]
    if unknown:
        raise ValueError(f"グループ {', '.join(unknown)} が見つかりません。")
    return {
        "email": email,
        "name": require_text(payload.get("name") or email.split("@")[0], "表示名", max_length=100),
        "role": role,
        "enabled": bool(payload.get("enabled", True)),
        "group_ids": group_ids,
    }


def _write_groups(conn: sqlite3.Connection, user_id: str, group_ids: list[str],
                  roles: dict[str, str] | None = None) -> None:
    """所属グループを書き換える。続けて所属するグループの役割はそのまま残し、新しいグループは roles か viewer にする。"""
    current = _group_roles(conn, user_id)
    conn.execute("DELETE FROM user_groups WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_groups (user_id, group_id, role) VALUES (?, ?, ?)",
        [(user_id, g, (roles or {}).get(g) or current.get(g) or "viewer") for g in group_ids],
    )


def _count_active_admins(conn: sqlite3.Connection, excluding: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND enabled = 1"
    params: list[Any] = []
    if excluding:
        query += " AND id != ?"
        params.append(excluding)
    return conn.execute(query, params).fetchone()[0]


def create_user(payload: dict[str, Any], *, group_roles: dict[str, str] | None = None) -> dict[str, Any]:
    """group_roles を渡すと、そのグループでの役割にする（渡さなければ viewer）。"""
    values = _validate(payload)
    user_id = new_id()
    now = to_iso(now_local())
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO users (id, email, name, role, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, values["email"], values["name"], values["role"], int(values["enabled"]), now, now),
            )
            _write_groups(conn, user_id, values["group_ids"], group_roles)
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じメールアドレスのユーザーがすでにいます。") from exc
    return get_user(user_id)


def update_user(user_id: str, payload: dict[str, Any], *, actor_email: str) -> dict[str, Any]:
    current = get_user(user_id)
    values = _validate({**current, **payload})
    is_self = current["email"] == normalize_email(actor_email)
    loses_admin = current["role"] == "admin" and (values["role"] != "admin" or not values["enabled"])
    if is_self and loses_admin:
        # 自分の権限を外すと、元に戻せる人がいなくなることがある
        raise ValueError("自分自身の管理者権限は外せません。別の管理者に依頼してください。")
    try:
        with connect() as conn:
            if loses_admin and _count_active_admins(conn, excluding=user_id) == 0:
                raise ValueError("有効な管理者がいなくなるため変更できません。先に別の管理者を登録してください。")
            conn.execute(
                "UPDATE users SET email = ?, name = ?, role = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (values["email"], values["name"], values["role"], int(values["enabled"]), to_iso(now_local()), user_id),
            )
            _write_groups(conn, user_id, values["group_ids"])
    except sqlite3.IntegrityError as exc:
        raise ValueError("同じメールアドレスのユーザーがすでにいます。") from exc
    return get_user(user_id)


def delete_user(user_id: str, *, actor_email: str) -> dict[str, Any]:
    current = get_user(user_id)
    if current["email"] == normalize_email(actor_email):
        raise ValueError("自分自身は削除できません。")
    with connect() as conn:
        if current["role"] == "admin" and current["enabled"] and _count_active_admins(conn, excluding=user_id) == 0:
            raise ValueError("有効な管理者がいなくなるため削除できません。")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return current


def principal_for(email: str) -> Principal | None:
    """ログイン中のユーザーを、今のロールと所属グループで組み立てる。無効・未登録なら None。"""
    record = find_by_email(email)
    if record is None or not record["enabled"]:
        return None
    permissions = record["permissions"]
    # 管理者は全グループを見る。所属グループを付け忘れても運用が止まらないように
    group_ids = None if permissions["can_manage_users"] else frozenset(record["group_ids"])
    return Principal(email=record["email"], name=record["name"], role=record["role"],
                     permissions=permissions, group_ids=group_ids, group_roles=dict(record["group_roles"]))


def record_login(email: str, display_name: str) -> None:
    """最終ログイン日時を残す。表示名が未設定なら Google の名前で埋める。"""
    with connect() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ?, name = CASE WHEN name = '' THEN ? ELSE name END WHERE email = ?",
            (to_iso(now_local()), display_name, normalize_email(email)),
        )


def ensure_bootstrap_admins(emails: tuple[str, ...]) -> list[str]:
    """環境変数で指定した人を管理者として登録する（いなければ）。

    ユーザーマスターが空だと誰もログインできず、画面から登録もできない。
    最初の 1 人を入れるための入口。すでにいる人のロールは変えない。
    """
    created = []
    for email in emails:
        if not _EMAIL_PATTERN.match(normalize_email(email)):
            continue
        if find_by_email(email) is not None:
            continue
        try:
            create_user({"email": email, "role": "admin", "enabled": True})
            created.append(normalize_email(email))
        except ValueError:
            # gunicorn の別の worker が同時に作った。もういるので、それでよい
            continue
    return created
