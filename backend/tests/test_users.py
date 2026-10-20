"""ユーザー・グループのマスター。"""
from __future__ import annotations

import pytest

from domain import groups, users
from tests.conftest import make_room, make_group


def test_create_user_normalizes_email_and_checks_groups():
    make_group("a")
    user = users.create_user({"email": " Op@Example.com ", "role": "user", "group_ids": ["a"]})
    assert user["email"] == "op@example.com"
    assert user["group_ids"] == ["a"]
    assert user["permissions"]["can_edit"] is False
    with pytest.raises(ValueError, match="グループ nope"):
        users.create_user({"email": "x@example.com", "group_ids": ["nope"]})
    with pytest.raises(ValueError, match="同じメールアドレス"):
        users.create_user({"email": "op@example.com"})


def test_principal_reflects_role_groups_and_enabled():
    make_group("a")
    user = users.create_user({"email": "p@example.com", "role": "power", "group_ids": ["a"]})
    principal = users.principal_for("P@example.com")
    assert principal.group_ids == frozenset({"a"}) and principal.can("can_edit")
    users.update_user(user["id"], {"enabled": False}, actor_email="admin@example.com")
    # 無効にしたら、次のリクエストから入れない
    assert users.principal_for("p@example.com") is None
    assert users.principal_for("unknown@example.com") is None


def test_admin_sees_all_groups():
    users.create_user({"email": "admin@example.com", "role": "admin"})
    assert users.principal_for("admin@example.com").group_ids is None


def test_cannot_remove_last_admin_or_demote_self():
    admin = users.create_user({"email": "admin@example.com", "role": "admin"})
    with pytest.raises(ValueError, match="自分自身"):
        users.update_user(admin["id"], {"role": "user"}, actor_email="admin@example.com")
    with pytest.raises(ValueError, match="管理者がいなくなる"):
        users.update_user(admin["id"], {"enabled": False}, actor_email="other@example.com")
    with pytest.raises(ValueError, match="自分自身は削除"):
        users.delete_user(admin["id"], actor_email="admin@example.com")
    users.create_user({"email": "second@example.com", "role": "admin"})
    users.update_user(admin["id"], {"role": "user"}, actor_email="second@example.com")


def test_bootstrap_admins_only_adds_missing():
    users.create_user({"email": "keep@example.com", "role": "user"})
    created = users.ensure_bootstrap_admins(("keep@example.com", "boss@example.com", "not-an-email"))
    assert created == ["boss@example.com"]
    assert users.find_by_email("keep@example.com")["role"] == "user"
    assert users.find_by_email("boss@example.com")["role"] == "admin"


def test_group_in_use_cannot_be_deleted():
    make_group("a")
    make_room(group_id="a")
    with pytest.raises(ValueError, match="ルーム 1 件"):
        groups.delete_group("a")
    make_group("empty")
    groups.delete_group("empty")


def test_group_id_format():
    with pytest.raises(ValueError, match="半角英数字"):
        groups.create_group({"id": "日本語", "name": "x"})


def test_bootstrap_tolerates_another_worker_creating_the_same_admin(monkeypatch):
    # 2 つの worker が同時に起動すると、確認と作成の間にもう片方が作っていることがある
    users.create_user({"email": "boss@example.com", "role": "admin"})
    monkeypatch.setattr(users, "find_by_email", lambda _email: None)
    assert users.ensure_bootstrap_admins(("boss@example.com",)) == []
