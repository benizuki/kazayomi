"""グループを自分で作る・招待で入る・グループ管理者がメンバーとルーム・デバイスを管理する。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.auth as auth
from core.auth import require_principal
from domain import groups, memberships, users
from domain.access import ForbiddenError
from main import app
from tests.conftest import make_group, make_jpeg, make_room


@pytest.fixture
def client(isolated_storage, monkeypatch):
    monkeypatch.setattr(auth, "google_oauth_client_id", lambda: "123-abc.apps.googleusercontent.com")
    yield TestClient(app)
    app.dependency_overrides.clear()


def sign_in(client: TestClient, monkeypatch, email: str, name: str = "新人"):
    monkeypatch.setattr(auth, "_verify_google_credential",
                        lambda _c: {"email": email, "email_verified": True, "name": name})
    return client.post("/auth/google", json={"credential": "dummy"})


def act_as(email: str) -> None:
    app.dependency_overrides[require_principal] = lambda: users.principal_for(email)


# ── ログイン画面 ─────────────────────────────────

def test_unregistered_person_cannot_create_group_from_login(client: TestClient, monkeypatch):
    """グループを作れるのはアプリの管理者だけ。誰でも作れると、誰でもメールアドレスを登録できてしまう。"""
    res = sign_in(client, monkeypatch, "Founder@Example.com", "創設者")
    assert res.status_code == 403 and "onboarding" not in res.json() and res.json()["error"] == "ログインできませんでした。"
    assert client.post("/auth/onboarding/group", json={"group_name": "g"}).status_code in (404, 405)
    assert users.list_users() == []
    # 登録されていない人のメールアドレスは、記録にも残さない
    from core.audit import list_auth_audit_logs
    assert "founder@example.com" not in str(list_auth_audit_logs(20))


def test_onboarding_needs_fresh_sign_in_and_json(client: TestClient, monkeypatch):
    make_group("a")
    invitation = memberships.invite("a", "new@example.com", "viewer", invited_by="o@example.com")
    assert client.post("/auth/onboarding/accept", json={"invitation_id": invitation["id"]}).status_code == 401
    sign_in(client, monkeypatch, "new@example.com")
    assert client.post("/auth/onboarding/accept", data={"invitation_id": invitation["id"]}).status_code == 415
    real_time = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real_time() + 16 * 60)
    assert client.post("/auth/onboarding/accept", json={"invitation_id": invitation["id"]}).status_code == 401


def test_accept_invitation_from_login(client: TestClient, monkeypatch):
    make_group("a", "ライン A")
    invitation = memberships.invite("a", "Guest@Example.com", "editor", invited_by="owner@example.com")
    onboarding = sign_in(client, monkeypatch, "guest@example.com", "ゲスト").json()["onboarding"]
    assert onboarding["invitations"][0]["id"] == invitation["id"]
    assert "invited_by" not in onboarding["invitations"][0]

    res = client.post("/auth/onboarding/accept", json={"invitation_id": invitation["id"]})
    assert res.status_code == 200 and res.json()["group_name"] == "ライン A"
    me = client.get("/api/me").json()
    assert me["group_roles"] == {"a": "editor"} and me["permissions"]["can_edit"]
    assert memberships.list_invitations("a") == []


def test_cannot_accept_someone_elses_or_expired_invitation(client: TestClient, monkeypatch):
    make_group("a")
    other = memberships.invite("a", "other@example.com", "viewer", invited_by="o@example.com")
    mine = memberships.invite("a", "me@example.com", "viewer", invited_by="o@example.com")
    sign_in(client, monkeypatch, "me@example.com")
    assert client.post("/auth/onboarding/accept", json={"invitation_id": other["id"]}).status_code == 404

    from core.db import connect
    with connect() as conn:
        conn.execute("UPDATE group_invitations SET expires_at = '2000-01-01T00:00:00+09:00' WHERE id = ?", (mine["id"],))
    assert memberships.invitations_for("me@example.com") == []
    res = client.post("/auth/onboarding/accept", json={"invitation_id": mine["id"]})
    assert res.status_code == 400 and "期限" in res.json()["error"]


def test_disabled_user_gets_no_onboarding(client: TestClient, monkeypatch):
    user = users.create_user({"email": "old@example.com"})
    users.update_user(user["id"], {"enabled": False}, actor_email="admin@example.com")
    res = sign_in(client, monkeypatch, "old@example.com")
    assert res.status_code == 403 and "onboarding" not in res.json() and res.json()["error"] == "ログインできませんでした。"


# ── グループ管理者 ───────────────────────────────

def owner_of_new_group(email: str = "owner@example.com") -> str:
    """アプリの管理者がグループを作り、最初のグループ管理者を入れたところ。"""
    group = groups.create_group({"id": "own", "name": "オーナーのライン"})
    users.create_user({"email": email, "name": "オーナー", "role": "user", "group_ids": [group["id"]]},
                      group_roles={group["id"]: "owner"})
    return group["id"]


def test_owner_invites_and_manages_members(client: TestClient):
    gid = owner_of_new_group()
    make_group("other")
    act_as("owner@example.com")

    res = client.post(f"/api/groups/{gid}/invitations", json={"email": "Member@example.com", "role": "viewer"})
    assert res.status_code == 201 and res.json()["email"] == "member@example.com"
    # 自分のグループ以外には招待できない
    assert client.post("/api/groups/other/invitations", json={"email": "x@example.com"}).status_code == 403
    assert [g["id"] for g in client.get("/api/groups/managed").json()] == [gid]

    # 登録済みの人は、画面の中で招待を受ける
    users.create_user({"email": "member@example.com", "group_ids": ["other"]})
    act_as("member@example.com")
    invitations = client.get("/api/me").json()["invitations"]
    assert [i["group_name"] for i in invitations] == ["オーナーのライン"]
    assert client.post(f"/api/invitations/{invitations[0]['id']}/accept").status_code == 200
    assert users.principal_for("member@example.com").group_roles == {"other": "viewer", gid: "viewer"}

    act_as("owner@example.com")
    member = users.find_by_email("member@example.com")
    res = client.put(f"/api/groups/{gid}/members/{member['id']}", json={"role": "owner"})
    assert res.status_code == 200 and res.json()["role"] == "owner"
    body = client.get(f"/api/groups/{gid}/members").json()
    assert [m["role"] for m in body["members"]] == ["owner", "owner"] and body["invitations"] == []

    # メンバーでないグループ（other）の役割は変えられない
    assert client.put(f"/api/groups/other/members/{member['id']}", json={"role": "owner"}).status_code == 403
    assert client.delete(f"/api/groups/{gid}/members/{member['id']}").status_code == 200
    assert gid not in users.principal_for("member@example.com").group_roles

    # 最後のグループ管理者は外せない・降ろせない
    owner = users.find_by_email("owner@example.com")
    assert "最後" in client.delete(f"/api/groups/{gid}/members/{owner['id']}").json()["error"]
    assert "いなくなる" in client.put(f"/api/groups/{gid}/members/{owner['id']}", json={"role": "viewer"}).json()["error"]


def test_editor_and_viewer_cannot_manage_members(client: TestClient):
    gid = owner_of_new_group()
    memberships.invite(gid, "editor@example.com", "editor", invited_by="owner@example.com")
    memberships.accept_invitation(memberships.invitations_for("editor@example.com")[0]["id"], "editor@example.com")
    act_as("editor@example.com")
    assert client.get(f"/api/groups/{gid}/members").status_code == 403
    assert client.post(f"/api/groups/{gid}/invitations", json={"email": "x@example.com"}).status_code == 403
    assert client.post("/api/masters/rooms", json={"name": "r", "ayame_room_id": "r-1", "group_id": gid}).status_code == 403


def test_owner_manages_rooms_and_devices_only_in_own_group(client: TestClient):
    gid = owner_of_new_group()
    make_group("other")
    other_room = make_room(name="よそ", ayame_room_id="other-1", group_id="other")
    act_as("owner@example.com")

    res = client.post("/api/masters/rooms", json={"name": "うちのルーム", "ayame_room_id": "mine-1", "group_id": gid})
    assert res.status_code == 201
    room = res.json()
    assert client.post("/api/masters/rooms", json={"name": "x", "ayame_room_id": "x-1", "group_id": "other"}).status_code == 403
    assert [r["id"] for r in client.get("/api/masters/rooms").json()] == [room["id"]]
    assert client.delete(f"/api/masters/rooms/{other_room['id']}").status_code == 403
    # 別のグループへは移せない
    assert client.put(f"/api/masters/rooms/{room['id']}", json={**room, "group_id": "other"}).status_code == 403
    assert [g["id"] for g in client.get("/api/masters/groups").json()] == [gid]

    # サーバは一覧だけ見られる
    assert client.get("/api/masters/servers").status_code == 200
    assert client.post("/api/masters/servers", json={"name": "s", "signaling_url": "wss://x/signaling"}).status_code == 403

    # デバイスは自分のグループのルームに付ける。ルームなしは作れない
    res = client.post("/api/masters/devices", json={"name": "端末1", "room_id": room["id"]})
    assert res.status_code == 201
    device = res.json()
    assert client.post("/api/masters/devices", json={"name": "端末2"}).status_code == 403
    assert client.post("/api/masters/devices", json={"name": "端末3", "room_id": other_room["id"]}).status_code == 403
    assert client.post(f"/api/masters/devices/{device['id']}/enrollment").status_code == 200

    # ほかのグループのデバイスは見えない・触れない
    app.dependency_overrides.clear()
    from domain import devices
    foreign = devices.create_device({"name": "よその端末", "room_id": other_room["id"]})
    act_as("owner@example.com")
    assert [d["id"] for d in client.get("/api/masters/devices").json()] == [device["id"]]
    assert client.delete(f"/api/masters/devices/{foreign['id']}").status_code == 403

    # ユーザー・グループの管理と監査ログは、アプリの管理者だけ
    for path in ("/api/masters/users", "/api/audit-logs"):
        assert client.get(path).status_code == 403


def test_edit_rights_follow_group_role(client: TestClient):
    """全体のロールが閲覧者でも、編集者として入ったグループでは編集できる。逆のグループではできない。"""
    from domain import albums, images

    make_group("a")
    make_group("b")
    users.create_user({"email": "mixed@example.com", "role": "user", "group_ids": ["a", "b"]},
                      group_roles={"a": "editor", "b": "viewer"})
    img_a = images.save_image(make_jpeg(), source="camera", group_id="a")
    img_b = images.save_image(make_jpeg(), source="camera", group_id="b")
    act_as("mixed@example.com")
    assert client.patch(f"/api/images/{img_a['id']}", json={"memo": "a"}).status_code == 200
    assert client.patch(f"/api/images/{img_b['id']}", json={"memo": "b"}).status_code == 403
    # お気に入りは閲覧者でも付けられる
    assert client.patch(f"/api/images/{img_b['id']}", json={"favorite": True}).status_code == 200
    # まとめて消すと、編集できるグループの画像だけが消える
    assert client.post("/api/images/delete", json={"ids": [img_a["id"], img_b["id"]]}).json() == {"deleted": 1}
    assert client.post("/api/albums", json={"name": "A のアルバム", "group_id": "a"}).status_code == 201
    res = client.post("/api/albums", json={"name": "B のアルバム", "group_id": "b"})
    assert res.status_code == 403
    album_b = albums.create_album({"name": "B", "group_id": "b"})
    assert client.patch(f"/api/albums/{album_b['id']}", json={"name": "変更"}).status_code == 403
    assert client.delete(f"/api/albums/{album_b['id']}").status_code == 403


def test_existing_global_roles_still_work():
    """移行前からいる人（グループでの役割は viewer）は、全体のロールで今までどおり動く。"""
    make_group("a")
    users.create_user({"email": "power@example.com", "role": "power", "group_ids": ["a"]})
    principal = users.principal_for("power@example.com")
    assert principal.group_roles == {"a": "viewer"}
    assert principal.can_in("a", "can_edit") and not principal.can_in("b", "can_edit")
    assert not principal.can_in("a", "can_manage_members")
    with pytest.raises(ForbiddenError):
        principal.require_in("a", "can_manage_devices")
    # アプリの管理者は、所属していないグループのメンバーも管理できる
    users.create_user({"email": "admin@example.com", "role": "admin"})
    assert users.principal_for("admin@example.com").can_in("a", "can_manage_members")
    assert groups.get_group("a")["user_count"] == 1


def test_users_master_keeps_group_roles():
    gid = owner_of_new_group()
    make_group("extra")
    owner = users.find_by_email("owner@example.com")
    users.update_user(owner["id"], {"group_ids": [gid, "extra"]}, actor_email="admin@example.com")
    assert users.get_user(owner["id"])["group_roles"] == {gid: "owner", "extra": "viewer"}


# ── グループの削除 ───────────────────────────────

def test_owner_deletes_group_with_contents(client: TestClient, isolated_storage):
    from domain import albums, devices, images

    gid = owner_of_new_group()
    room = make_room(name="消すルーム", ayame_room_id="gone-1", group_id=gid)
    device = devices.create_device({"name": "消す端末", "room_id": room["id"]})
    image = images.save_image(make_jpeg(), source="camera", group_id=gid, room=room)
    album = albums.create_album({"name": "消すアルバム", "group_id": gid})
    albums.add_items(album["id"], [image["id"]])
    memberships.invite(gid, "pending@example.com", "viewer", invited_by="owner@example.com")
    users.create_user({"email": "member@example.com", "group_ids": [gid, "default"]})
    users.create_user({"email": "only-here@example.com", "group_ids": [gid]})
    users.create_user({"email": "power@example.com", "role": "power", "group_ids": [gid]})
    kept = images.save_image(make_jpeg(), source="camera", group_id="default")
    def image_files() -> int:
        return sum(1 for p in isolated_storage.rglob("*.jpg") if p.is_file())
    files_before = image_files()

    act_as("owner@example.com")
    assert client.get(f"/api/groups/{gid}/contents").json() == {
        "rooms": 1, "devices": 1, "images": 1, "albums": 1, "members": 4, "users_deleted": 2, "invitations": 1}
    # グループ名が合わなければ消さない
    res = client.post(f"/api/groups/{gid}/delete", json={"confirm_name": "ちがう"})
    assert res.status_code == 400 and groups.exists(gid)

    res = client.post(f"/api/groups/{gid}/delete", json={"confirm_name": "オーナーのライン"})
    assert res.status_code == 200 and res.json()["deleted"]["images"] == 1 and res.json()["self_deleted"] is True
    assert not groups.exists(gid)
    with pytest.raises(Exception):
        devices.get_device(device["id"])
    assert memberships.invitations_for("pending@example.com") == []
    # 画像のファイル（本体とサムネイル）も消える。ほかのグループの画像は残る
    assert files_before >= 4 and image_files() == files_before - 2
    assert images.get_image(kept["id"])["id"] == kept["id"]
    # このグループにしか入っていない閲覧者（全体のロール）は、アカウントごと消える（消した本人も）
    assert users.find_by_email("only-here@example.com") is None
    assert users.find_by_email("owner@example.com") is None
    # ほかのグループにも入っている人と、アプリの管理者が役割を付けた人は残る
    assert users.find_by_email("member@example.com")["group_ids"] == ["default"]
    assert users.find_by_email("power@example.com")["group_ids"] == []
    deleted = [log["target"] for log in memberships_audit() if log["event"] == "user.delete"]
    assert sorted(deleted) == ["only-here@example.com", "owner@example.com"]
    assert "group.delete" in [log["event"] for log in memberships_audit()]


def memberships_audit():
    from core.audit import list_auth_audit_logs
    return list_auth_audit_logs(50)


def test_only_owner_can_delete_group_and_default_is_protected(client: TestClient):
    gid = owner_of_new_group()
    memberships.invite(gid, "editor@example.com", "editor", invited_by="owner@example.com")
    memberships.accept_invitation(memberships.invitations_for("editor@example.com")[0]["id"], "editor@example.com")
    act_as("editor@example.com")
    assert client.post(f"/api/groups/{gid}/delete", json={"confirm_name": "オーナーのライン"}).status_code == 403
    assert groups.exists(gid)

    users.create_user({"email": "admin@example.com", "role": "admin"})
    act_as("admin@example.com")
    res = client.post("/api/groups/default/delete", json={"confirm_name": "既定のグループ"})
    assert res.status_code == 400 and groups.exists("default")


# ── 容量 ─────────────────────────────────────────

def test_group_quota_blocks_uploads_and_counts_usage(client: TestClient):
    from domain import images

    make_group("q", "容量のテスト")
    first = images.save_image(make_jpeg(), source="camera", group_id="q")
    group = groups.get_group("q")
    assert group["image_count"] == 1 and group["quota_bytes"] is None
    # サムネイルも使用量に数える
    assert group["usage_bytes"] > first["size_bytes"]

    # 上限ちょうどまでは入り、超えると止まる
    groups.update_group("q", {"name": "容量のテスト", "quota_bytes": group["usage_bytes"] + 1})
    with pytest.raises(images.QuotaExceededError, match="容量の上限"):
        images.save_image(make_jpeg(), source="camera", group_id="q")
    assert groups.get_group("q")["image_count"] == 1
    # ほかのグループには効かない
    images.save_image(make_jpeg(), source="camera", group_id="default")

    # 名前だけ変えても上限は残る。空にすると無制限
    groups.update_group("q", {"name": "改名"})
    assert groups.get_group("q")["quota_bytes"] == group["usage_bytes"] + 1
    groups.update_group("q", {"name": "改名", "quota_bytes": None})
    images.save_image(make_jpeg(), source="camera", group_id="q")


def test_quota_error_reaches_kazami_as_507(client: TestClient):
    from domain import devices
    from tests.test_devices import _enrolled

    make_group("q", "容量のテスト")
    room = make_room(name="r", ayame_room_id="r-1", group_id="q")
    groups.update_group("q", {"name": "容量のテスト", "quota_bytes": 10})
    _, kazami = _enrolled("端末", room["id"])
    token = kazami.login()["access_token"]
    res = client.post("/api/devices/images", headers={"Authorization": f"Bearer {token}"},
                      files={"image": ("a.jpg", make_jpeg(), "image/jpeg")})
    assert res.status_code == 507 and "容量の上限" in res.json()["error"]
    del devices


def test_default_quota_for_new_groups(client: TestClient):
    users.create_user({"email": "admin@example.com", "role": "admin"})
    act_as("admin@example.com")
    # 決めていないときは 100MB
    assert client.get("/api/masters/settings").json() == {"default_group_quota_bytes": 100 * 1024 * 1024}
    assert client.put("/api/masters/settings", json={"default_group_quota_bytes": 5 * 1024**3}).status_code == 200
    # 管理者が作るグループは、この上限で始まる
    own = client.post("/api/masters/groups", json={"id": "x", "name": "自分の"}).json()
    assert own["quota_bytes"] == 5 * 1024**3
    users.create_user({"email": "new@example.com", "group_ids": ["x"]}, group_roles={"x": "owner"})
    assert client.put("/api/masters/settings", json={"default_group_quota_bytes": -1}).status_code == 400
    # 無制限にすると、初期値には戻らない
    client.put("/api/masters/settings", json={"default_group_quota_bytes": None})
    assert client.get("/api/masters/settings").json()["default_group_quota_bytes"] is None
    client.put("/api/masters/settings", json={"default_group_quota_bytes": 5 * 1024**3})

    # グループ管理者は使用量を見られるが、上限は変えられない
    act_as("new@example.com")
    managed = client.get("/api/groups/managed").json()
    assert managed[0]["quota_bytes"] == 5 * 1024**3 and managed[0]["usage_bytes"] == 0
    assert client.put(f"/api/masters/groups/{own['id']}", json={"name": "自分の", "quota_bytes": None}).status_code == 403
    assert client.get("/api/masters/settings").status_code == 403
