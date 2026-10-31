"""HTTP 層のテスト。ログイン・権限・Kazami からのアップロードのように、取り決めそのものを確かめる。"""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from core.auth import require_principal
from domain import images
from main import app
from tests.conftest import make_room, make_group, make_jpeg, principal


@pytest.fixture
def client(isolated_storage):
    # lifespan は使わない（autouse のフィクスチャで保存先を差し替え済みのため）
    yield TestClient(app)
    app.dependency_overrides.clear()


def login_as(viewer) -> None:
    app.dependency_overrides[require_principal] = lambda: viewer


def test_api_requires_login(client: TestClient):
    for path in ("/api/me", "/api/rooms", "/api/images", "/api/albums", "/api/masters/users"):
        res = client.get(path)
        assert res.status_code == 401, path
        assert res.json()["error"].startswith("ログインが必要")
    assert client.get("/healthz").status_code == 200


def test_pages_redirect_to_login(client: TestClient):
    res = client.get("/library?camera=x", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/login?next=/library%3Fcamera%3Dx"


def test_login_page_escapes_redirect_and_rejects_external(client: TestClient):
    page = client.get('/login?next=/"><script>alert(1)</script>').text
    assert "<script>alert(1)" not in page
    assert 'data-redirect="/"' in client.get("/login?next=//evil.example.com").text
    assert 'data-redirect="/"' in client.get("/login?next=%2F%5Cevil.example").text


def test_safe_redirect_turns_anything_external_into_root():
    from core.auth import safe_redirect

    for bad in ("//evil.example", "/\\evil.example", "/\\/evil.example", "/\t/evil.example", "/\n/evil.example",
                "/\r/evil.example", "/\x00/evil.example", "https://evil.example", "javascript:alert(1)", "", None):
        assert safe_redirect(bad) == "/", repr(bad)
    for ok in ("/", "/rooms", "/library?room=x&tag=%E3%81%82", "/albums#top"):
        assert safe_redirect(ok) == ok


def test_cross_site_writes_are_rejected(client: TestClient):
    login_as(principal("admin"))
    # よそのサイト（同じサイトの別のサブドメインを含む）からのログアウトの強制は 403。セッションも消さない
    evil = client.post("/logout", headers={"Origin": "https://evil.testserver"})
    assert evil.status_code == 403
    assert "set-cookie" not in evil.headers
    assert client.post("/logout", headers={"Origin": "null"}).status_code == 403
    assert client.post("/logout", headers={"Origin": "http://["}).status_code == 403
    # text/plain のフォームで JSON を組み立てても、Origin で止める
    forged = client.post("/api/masters/users", content='{"email":"x@example.com","role":"admin","pad":"=1"}',
                         headers={"Origin": "https://evil.example", "Content-Type": "text/plain"})
    assert forged.status_code == 403
    assert client.delete("/api/albums/x", headers={"Origin": "https://evil.example"}).status_code == 403
    # 同じ Origin と、Origin の無いもの（Kazami・Ayame の Webhook）は通す
    assert client.post("/logout", headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/logout").status_code == 200
    # 読むだけの要求は Origin を見ない
    assert client.get("/healthz", headers={"Origin": "https://evil.example"}).status_code == 200


def test_cors_allowed_origin_can_write(client: TestClient, monkeypatch):
    from config.settings import get_settings

    monkeypatch.setattr(get_settings(), "allowed_origins", ("http://localhost:5173",))
    assert client.post("/logout", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_unregistered_google_user_is_rejected(client: TestClient, monkeypatch):
    import core.auth as auth

    monkeypatch.setattr(auth, "_verify_google_credential",
                        lambda _c: {"email": "stranger@example.com", "email_verified": True, "name": "x"})
    res = client.post("/auth/google", json={"credential": "dummy"})
    # 未登録の人は入れない（招待を受けると入れる。tests/test_memberships.py）
    assert res.status_code == 403
    assert res.json()["error"] == "ログインできませんでした。" and "onboarding" not in res.json()
    assert client.get("/api/me").status_code == 401


def test_registered_google_user_gets_session(client: TestClient, monkeypatch):
    import core.auth as auth
    from domain import users

    users.create_user({"email": "op@example.com", "role": "user", "group_ids": ["default"]})
    monkeypatch.setattr(auth, "google_oauth_client_id", lambda: "123-abc.apps.googleusercontent.com")
    monkeypatch.setattr(auth, "_verify_google_credential",
                        lambda _c: {"email": "Op@example.com", "email_verified": True, "name": "オペレーター"})
    assert client.post("/auth/google", json={"credential": "dummy"}).status_code == 200
    me = client.get("/api/me").json()
    assert me["user"]["email"] == "op@example.com"
    assert me["role"] == "user"
    assert me["groups"] == [{"id": "default", "name": "既定のグループ"}]
    # 無効にしたら、セッションが残っていても次のリクエストで弾く
    user = users.find_by_email("op@example.com")
    users.update_user(user["id"], {"enabled": False}, actor_email="admin@example.com")
    assert client.get("/api/me").status_code == 401


def test_permissions_are_enforced(client: TestClient):
    login_as(principal("user", {"default"}))
    assert client.get("/api/masters/users").status_code == 403
    assert client.post("/api/masters/rooms", json={}).status_code == 403
    assert client.post("/api/albums", json={"name": "A"}).status_code == 403
    assert client.post("/api/images/tags/batch", json={"ids": ["x"], "tags": ["a"]}).status_code == 403

    login_as(principal("device_admin", {"default"}))
    assert client.get("/api/masters/users").status_code == 403
    assert client.get("/api/masters/rooms").status_code == 200


def test_master_changes_are_audited(client: TestClient):
    login_as(principal("admin", email="boss@example.com"))
    assert client.post("/api/masters/groups", json={"id": "line", "name": "ライン"}).status_code == 201
    assert client.post("/api/masters/users", json={"email": "op@example.com", "role": "user", "group_ids": ["line"]}).status_code == 201
    logs = client.get("/api/audit-logs").json()
    events = [(log["event"], log["email"], log["target"]) for log in logs]
    assert ("user.create", "boss@example.com", "op@example.com") in events
    assert ("group.create", "boss@example.com", "line") in events


def test_capture_upload_with_bearer_token(client: TestClient):
    login_as(principal())
    room = make_room("c", "c")
    issued = client.post("/api/captures", json={"room_id": room["id"]}).json()
    app.dependency_overrides.clear()  # Kazami はログインしない

    url = f"/api/captures/{issued['capture_id']}/image"
    files = {"image": ("image.jpg", make_jpeg(), "image/jpeg")}
    data = {"capturedAt": "2026-10-14T10:00:00.000+09:00"}
    denied = client.post(url, files=files, data=data)
    assert denied.status_code == 401
    ok = client.post(url, files=files, data=data, headers={"Authorization": f"Bearer {issued['token']}"})
    assert ok.status_code == 201
    assert ok.json()["date_key"] == "20261014"

    login_as(principal())
    assert client.get(f"/api/captures/{issued['capture_id']}").json() == {
        "capture_id": issued["capture_id"], "status": "done", "image_id": ok.json()["id"]}
    # 撮像 ID を知っていても、ほかのグループの人には中身を出さない
    login_as(principal("user", {"other"}))
    assert client.get(f"/api/captures/{issued['capture_id']}").json() == {
        "capture_id": issued["capture_id"], "status": "expired"}


def test_other_groups_images_are_hidden(client: TestClient):
    make_group("a")
    make_group("b")
    hidden = {}
    for group_id in ("a", "b"):
        hidden[group_id] = images.save_image(make_jpeg(), source="camera", group_id=group_id)
    login_as(principal("power", {"a"}))
    listed = client.get("/api/images").json()["items"]
    assert {i["group_id"] for i in listed} == {"a"}
    other = [i for i in client.get("/api/images", params={"group_id": "a"}).json()["items"]]
    assert len(other) == 1
    assert client.get("/api/images", params={"group_id": "b"}).status_code == 403
    assert client.get(f"/api/images/{hidden['b']['id']}").status_code == 404


def test_errors_use_one_shape(client: TestClient):
    login_as(principal())
    res = client.post("/api/masters/rooms", json={"name": "", "ayame_room_id": "x", "group_id": "default"})
    assert res.status_code == 400
    assert res.json()["error"] == "ルーム名を入力してください。"
    missing = client.get("/api/images/nope")
    assert missing.status_code == 404 and "error" in missing.json()


def test_csp_allows_signaling_origin_google_and_microphone(client: TestClient):
    from domain import servers
    servers.create_server({"name": "A", "signaling_url": "wss://ayame.example.com/signaling", "is_default": True})
    servers.invalidate_origin_cache()
    headers = client.get("/healthz").headers
    # マスターのサーバの Origin を許す
    assert "wss://ayame.example.com" in headers["Content-Security-Policy"]
    assert "https://accounts.google.com" in headers["Content-Security-Policy"]
    assert "microphone=(self)" in headers["Permissions-Policy"]


def test_zip_download_has_japanese_filename(client: TestClient):
    login_as(principal())
    album = client.post("/api/albums", json={"name": "アルバム", "group_id": "default"}).json()
    image = images.save_image(make_jpeg(), source="camera", group_id="default")
    client.post(f"/api/albums/{album['id']}/items", json={"ids": [image["id"]]})
    res = client.get(f"/api/albums/{album['id']}/export")
    assert res.status_code == 200
    assert "filename*=UTF-8''%E3%82%A2" in res.headers["content-disposition"]


def test_audit_logs_older_than_retention_are_purged(isolated_storage):
    """監査ログ（IP アドレスなどを含む）は、保存期間を過ぎたら消す。"""
    import json
    from datetime import datetime, timedelta, timezone

    from core import audit

    path = isolated_storage / "audit_logs.jsonl"
    now = datetime.now(timezone.utc)
    old = {"timestamp": (now - timedelta(days=91)).isoformat(), "event": "auth.login", "remote_ip": "203.0.113.1"}
    recent = {"timestamp": (now - timedelta(days=89)).isoformat(), "event": "auth.login", "remote_ip": "203.0.113.2"}
    path.write_text(json.dumps(old) + "\n" + json.dumps(recent) + "\n", encoding="utf-8")
    rotated = isolated_storage / "audit_logs.jsonl.1"
    rotated.write_text(json.dumps(old) + "\n", encoding="utf-8")

    audit.configure(path, retention_days=90)
    assert "203.0.113.1" not in path.read_text(encoding="utf-8")
    assert "203.0.113.2" in path.read_text(encoding="utf-8")
    assert not rotated.exists()
    assert [log["remote_ip"] for log in audit.list_auth_audit_logs(10)] == ["203.0.113.2"]

    # 書き足しても、消えた記録は戻らない
    audit.record_operation(actor_email="a@example.com", event="x", target="y")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_login_assets_are_not_cached_and_versioned(client: TestClient):
    """Cloudflare などに古いスクリプトを持たれないように、毎回確かめさせ、URL に版を付ける。"""
    import re

    page = client.get("/login").text
    version = re.search(r'/auth/login\.js\?v=([0-9a-f]{12})', page)
    assert version, "login.js の URL に版が付いていない"
    res = client.get(f"/auth/login.js?v={version.group(1)}")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-cache"


def test_server_api_never_returns_or_logs_turn_token(client: TestClient, isolated_storage):
    login_as(principal("admin"))
    res = client.post("/api/masters/servers", json={
        "name": "CF", "signaling_url": "wss://ayame.example.com/signaling", "kind": "cloudflare",
        "turn_key_id": "key-1", "turn_api_token": "secret-token",
    })
    assert res.status_code == 201
    server = res.json()
    assert server["kind"] == "cloudflare" and server["turn_api_token_set"] is True
    res = client.put(f"/api/masters/servers/{server['id']}", json={**server, "turn_api_token": ""})
    assert res.status_code == 200 and res.json()["turn_api_token_set"] is True
    listed = client.get("/api/masters/servers").text
    assert "secret-token" not in listed
    assert "secret-token" not in (isolated_storage / "audit_logs.jsonl").read_text()


def test_enrollment_qr_uses_server_decided_api_url(client: TestClient, monkeypatch):
    import json

    from config.settings import get_settings
    from domain import devices

    login_as(principal("admin"))
    device = devices.create_device({"name": "端末1", "room_id": make_room()["id"]})
    path = f"/api/masters/devices/{device['id']}/enrollment"

    # PUBLIC_BASE_URL があれば、それを https://ホスト の形にそろえて入れる。リクエストの Host は使わない
    monkeypatch.setattr(get_settings(), "public_base_url", "https://kazayomi.example.com/")
    body = client.post(path, headers={"X-Forwarded-Host": "evil.example"}).json()
    assert body["api_url"] == "https://kazayomi.example.com"
    assert json.loads(body["qr_text"]) == {"v": 1, "api": "https://kazayomi.example.com", "token": body["token"], "name": "端末1"}

    # 無ければ今のリクエストから組み立てる。Kazami が読めない形なら、トークンを出さずに断る
    monkeypatch.setattr(get_settings(), "public_base_url", "")
    assert client.post(path).json()["api_url"] == "http://testserver"
    res = client.post(path, headers={"X-Forwarded-Host": "kazayomi.example.com/evil"})
    assert res.status_code == 400
    assert "PUBLIC_BASE_URL" in res.json()["error"]
