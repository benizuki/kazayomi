"""ゲスト。ログイン画面で「ゲストとして試す」を選び、ニックネームと利用規約への同意だけで始める人。

モードの切り替えはない。登録されている人は全部の機能を、ゲストは一時的なルームだけを、同じ kazayomi で使う。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.auth as auth
from config.settings import get_settings
from domain import app_settings, devices, guest_rooms, room_access, servers, users
from main import app
from tests.conftest import make_group, make_jpeg, make_room
from tests.test_devices import FakeKazami


@pytest.fixture
def client(isolated_storage, monkeypatch):
    monkeypatch.setattr(auth, "google_oauth_client_id", lambda: "123-abc.apps.googleusercontent.com")
    servers.create_server({"name": "Ayame", "signaling_url": "wss://ayame.example.com/signaling", "is_default": True})
    yield TestClient(app)


def sign_in(client: TestClient, monkeypatch, email: str = "member@example.com"):
    """登録されている人の Google ログイン。"""
    monkeypatch.setattr(auth, "_verify_google_credential",
                        lambda _c: {"sub": "123", "email": email, "email_verified": True, "name": "メンバー"})
    return client.post("/auth/google", json={"credential": "dummy"})


def start_guest(client: TestClient, nickname: str = "たろう", **extra):
    payload = {"nickname": nickname, "agree": True, "version": guest_rooms.TERMS_VERSION, **extra}
    return client.post("/auth/guest", json=payload)


def guest(client: TestClient, nickname: str = "たろう") -> TestClient:
    """ゲストとして始める（ニックネームと同意だけ。Google ログインは使わない）。"""
    assert start_guest(client, nickname).json() == {"ok": True, "guest": True}
    return client


def kazami_call(client: TestClient, kazami: FakeKazami) -> dict:
    """Kazami と同じく HTTP で認証する。"""
    res = client.post("/api/devices/challenge", json={"device_id": kazami.device_id})
    if res.status_code != 200:
        return {"status": res.status_code, **res.json()}
    challenge = res.json()["challenge"]
    res = client.post("/api/devices/token", json={
        "device_id": kazami.device_id, "signature": kazami.sign(devices.auth_message(challenge, kazami.device_id))})
    return res.json() if res.status_code == 200 else {"status": res.status_code, **res.json()}


# ── 始め方 ─────────────────────────────────────────

def test_guest_starts_with_nickname_only_and_keeps_nothing(client: TestClient):
    assert start_guest(client, "  たろう  ").json() == {"ok": True, "guest": True}
    me = client.get("/api/me").json()
    assert me["guest"] is True and me["user"] == {"email": "", "name": "たろう", "picture": ""}
    # 始めるときに同意しているので、同意の画面は出ない
    assert me["consent"]["required"] is False
    # ユーザーのマスターに行を作らず、記録にもニックネームを残さない
    assert users.list_users() == []
    from core.audit import list_auth_audit_logs
    assert "たろう" not in str(list_auth_audit_logs(50))


def test_guest_start_needs_nickname_consent_and_json(client: TestClient):
    assert start_guest(client, "").status_code == 400
    assert start_guest(client, "あ" * 31).status_code == 400
    assert start_guest(client, agree=False).status_code == 400
    assert start_guest(client, version="old").status_code == 400
    assert client.post("/auth/guest", data={"nickname": "x", "agree": "true"}).status_code == 415
    assert client.get("/api/me").status_code == 401


def test_guest_starts_are_rate_limited_per_client(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "guest_starts_per_hour", 2)
    assert start_guest(client).status_code == 200
    assert start_guest(client).status_code == 200
    res = start_guest(client)
    assert res.status_code == 429 and "しばらく待って" in res.json()["error"]


def test_terms_change_asks_for_consent_again(client: TestClient, monkeypatch):
    guest(client)
    monkeypatch.setattr(guest_rooms, "TERMS_VERSION", "2099-01-01")
    assert client.get("/api/me").json()["consent"] == {"required": True, "version": "2099-01-01"}
    assert client.get("/api/guest/room").status_code == 403
    assert client.post("/api/guest/consent", json={"version": "2099-01-01"}).status_code == 200
    assert client.get("/api/guest/room").status_code == 200


def test_unregistered_google_account_is_not_a_guest(client: TestClient, monkeypatch):
    """Google ログインはメンバーのため。登録されていない人は、ゲストの入口を使う。"""
    res = sign_in(client, monkeypatch, email="stranger@example.com")
    assert res.status_code == 403 and "ゲストとして試す" in res.json()["error"]
    assert client.get("/api/me").status_code == 401


def test_registered_users_are_not_guests(client: TestClient, monkeypatch):
    users.create_user({"email": "member@example.com", "group_ids": ["default"]})
    sign_in(client, monkeypatch)
    me = client.get("/api/me").json()
    assert me["guest"] is False and "consent" not in me
    # 一時的なルームはゲストだけ
    assert client.get("/api/guest/room").status_code == 403


def test_guest_can_be_turned_off(client: TestClient):
    app_settings.update({"guest_enabled": False})
    res = start_guest(client)
    assert res.status_code == 403 and "受け付けていません" in res.json()["error"]
    assert 'data-guest-enabled="false"' in client.get("/login").text
    # 始めたあとに止めると、次のリクエストから入れない
    app_settings.update({"guest_enabled": True})
    guest(client)
    app_settings.update({"guest_enabled": False})
    assert client.get("/api/me").status_code == 401


# ── 一時的なルーム ─────────────────────────────────

def test_guest_room_is_one_per_guest(client: TestClient):
    guest(client)
    room = client.get("/api/guest/room").json()
    assert client.get("/api/guest/room").json()["id"] == room["id"]
    assert room["ayame_room_id"].startswith("guest-") and room["device"] is None and room["signaling_ready"]


def test_guest_cannot_use_group_features(client: TestClient):
    make_group("a")
    make_room(name="よそ", ayame_room_id="other-1", group_id="a")
    guest(client)
    for path in ("/api/images", "/api/albums", "/api/masters/users", "/api/groups/managed", "/api/rooms",
                 "/api/masters/servers", "/api/audit-logs"):
        assert client.get(path).status_code == 403, path


def test_kazami_enrolls_into_guest_room_and_ayame_checks_it(client: TestClient):
    guest(client)
    room = client.get("/api/guest/room").json()
    qr = client.post("/api/guest/room/enrollment").json()
    assert qr["api"].startswith("http") and qr["token"]

    kazami = FakeKazami()
    assert client.post("/api/devices/enroll", json=kazami.enroll_payload(qr["token"])).status_code == 200
    assert client.get("/api/guest/room").json()["device"]["enrolled"] is True
    config = kazami_call(client, kazami)
    assert config["room"]["ayame_room_id"] == room["ayame_room_id"]
    assert config["signaling_url"] == "wss://ayame.example.com/signaling"
    assert config["can_upload_captures"] is False  # Kazami は本体の撮像ボタンを出さない

    # Ayame の認証 Webhook: 登録した Kazami と、持ち主のブラウザ（チケット）だけを通す
    device_key = config["signaling_key"]
    assert room_access.authenticate({"roomId": room["ayame_room_id"], "signalingKey": device_key})["allowed"]
    assert not room_access.authenticate({"roomId": "guest-other", "signalingKey": device_key})["allowed"]
    ticket = client.post("/api/guest/room/ticket").json()["ticket"]
    assert room_access.authenticate({"roomId": room["ayame_room_id"], "signalingKey": ticket})["allowed"]

    # 画像は預からない
    res = client.post("/api/devices/images", headers={"Authorization": f"Bearer {device_key}"},
                      files={"image": ("a.jpg", make_jpeg(), "image/jpeg")})
    assert res.status_code == 403 and "保存しません" in res.json()["error"]

    # 終了すると、Kazami はつなげなくなり、次の QR を待つ
    assert client.delete("/api/guest/room").status_code == 200
    assert not room_access.authenticate({"roomId": room["ayame_room_id"], "signalingKey": device_key})["allowed"]
    assert kazami_call(client, kazami)["status"] == 401
    assert client.get("/api/guest/room").json()["id"] != room["id"]


def test_group_devices_and_guest_devices_live_together(client: TestClient):
    """同じ kazayomi で、グループのデバイスとゲストの端末がそれぞれ動く。取り合わない。"""
    room = make_room(name="ライン1", ayame_room_id="line-1")
    group_device = devices.create_device({"name": "ライン1 の iPhone", "room_id": room["id"]})
    group_kazami = FakeKazami("GROUP-0000-1111")
    devices.enroll(group_kazami.enroll_payload(devices.issue_enrollment(group_device["id"])["token"]))

    guest(client)
    client.get("/api/guest/room")
    guest_kazami = FakeKazami("GUEST-0000-2222")
    qr = client.post("/api/guest/room/enrollment").json()
    client.post("/api/devices/enroll", json=guest_kazami.enroll_payload(qr["token"]))

    assert kazami_call(client, group_kazami)["room"]["ayame_room_id"] == "line-1"
    assert kazami_call(client, guest_kazami)["room"]["ayame_room_id"].startswith("guest-")

    # グループのデバイスは、ゲストの QR では登録できない
    qr = client.post("/api/guest/room/enrollment").json()
    res = client.post("/api/devices/enroll", json=group_kazami.enroll_payload(qr["token"]))
    assert res.status_code == 400 and "グループのデバイス" in res.json()["error"]
    assert kazami_call(client, group_kazami)["room"]["ayame_room_id"] == "line-1"

    # ゲストの端末をグループのデバイスとして登録し直すと、ゲストのルームから外れる
    other = devices.create_device({"name": "もう 1 台", "room_id": room["id"]})
    client.post("/api/devices/enroll", json=guest_kazami.enroll_payload(devices.issue_enrollment(other["id"])["token"]))
    assert client.get("/api/guest/room").json()["device"] is None
    assert kazami_call(client, guest_kazami)["room"]["ayame_room_id"] == "line-1"


def test_rooms_are_separate_per_guest(client: TestClient):
    guest(client, "aaa")
    first = client.get("/api/guest/room").json()
    other = guest(TestClient(app), "aaa")  # 同じニックネームでも別のゲスト
    second = other.get("/api/guest/room").json()
    assert first["id"] != second["id"]
    # 他人のルームのチケットは取れない（自分のルームのチケットしか出ない）
    ticket = other.post("/api/guest/room/ticket").json()["ticket"]
    assert not room_access.authenticate({"roomId": first["ayame_room_id"], "signalingKey": ticket})["allowed"]


def test_kazami_moves_to_new_room_when_scanning_again(client: TestClient):
    kazami = FakeKazami()
    seen = []
    for nickname in ("aaa", "bbb"):
        c = guest(TestClient(app), nickname)
        c.get("/api/guest/room")
        qr = c.post("/api/guest/room/enrollment").json()
        c.post("/api/devices/enroll", json=kazami.enroll_payload(qr["token"]))
        seen.append((c, kazami_call(c, kazami)["room"]["ayame_room_id"]))
    (first_client, first_room), (_, second_room) = seen
    assert first_room != second_room
    assert first_client.get("/api/guest/room").json()["device"] is None


def test_legal_pages(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_name", "kazayomi 運営<script>")
    page = client.get("/terms").text
    assert "利用規約" in page and "kazayomi 運営&lt;script&gt;" in page
    assert "プライバシーポリシー" in client.get("/privacy").text
    login = client.get("/login").text
    assert 'data-guest-enabled="true"' in login and f'data-terms-version="{guest_rooms.TERMS_VERSION}"' in login


# ── 続きから使う ───────────────────────────────────

def reopen_browser(client: TestClient) -> TestClient:
    """ブラウザを閉じて開き直したところ（ログインのセッションは切れ、続きから使う Cookie だけが残る）。"""
    cookie = client.cookies.get(auth.GUEST_COOKIE)
    assert cookie, "続きから使う Cookie が出ていない"
    return TestClient(app, cookies={auth.GUEST_COOKIE: cookie})


def test_guest_comes_back_to_same_room_after_reopening_browser(client: TestClient):
    guest(client, "たろう")
    room = client.get("/api/guest/room").json()
    again = reopen_browser(client)
    me = again.get("/api/me").json()
    assert me["guest"] is True and me["user"]["name"] == "たろう"
    assert again.get("/api/guest/room").json()["id"] == room["id"]
    # ログイン画面を開いても、そのまま戻る
    assert again.get("/login", follow_redirects=False).status_code == 302


def test_guest_cookie_is_signed_and_cleared_on_logout(client: TestClient):
    guest(client)
    forged = TestClient(app, cookies={auth.GUEST_COOKIE: "eyJnaWQiOiJ4In0.forged.sig"})
    assert forged.get("/api/me").status_code == 401
    # ログアウトすると消える（共用の PC で、次の人が入らないように）
    res = client.post("/logout")
    assert auth.GUEST_COOKIE in res.headers.get("set-cookie", "")
    assert not client.cookies.get(auth.GUEST_COOKIE)
    assert client.get("/api/me").status_code == 401


def test_guest_cookie_expires_with_room_and_respects_guest_switch(client: TestClient, monkeypatch):
    guest(client)
    cookie = client.cookies.get(auth.GUEST_COOKIE)
    app_settings.update({"guest_enabled": False})
    assert TestClient(app, cookies={auth.GUEST_COOKIE: cookie}).get("/api/me").status_code == 401
    app_settings.update({"guest_enabled": True})
    # ルームの期限（最後に使ってから）を過ぎた Cookie は使えない
    monkeypatch.setattr(get_settings(), "guest_room_ttl_seconds", -1)
    assert TestClient(app, cookies={auth.GUEST_COOKIE: cookie}).get("/api/me").status_code == 401


# ── 再開コード ───────────────────────────────────

def resume(client: TestClient, code: str, nickname: str = "たろう"):
    return client.post("/auth/guest/resume", json={"code": code, "nickname": nickname})


def test_resume_code_brings_guest_back_after_logout_and_on_other_browser(client: TestClient):
    guest(client, "たろう")
    room = client.get("/api/guest/room").json()
    code = room["resume_code"]
    assert len(code) == 14 and code.count("-") == 2
    # 開き直しても同じコード
    assert client.get("/api/guest/room").json()["resume_code"] == code

    # ログアウトしてもルームは残る。コードで戻れる（小文字やハイフンなしでもよい）
    client.post("/logout")
    assert client.get("/api/me").status_code == 401
    assert resume(client, code.replace("-", "").lower(), "たろう2").json() == {"ok": True, "guest": True}
    again = client.get("/api/guest/room").json()
    assert again["id"] == room["id"] and again["resume_code"] == code
    assert client.get("/api/me").json()["user"]["name"] == "たろう2"

    # 別のブラウザからも戻れる。どちらも同じルームを見る
    other = TestClient(app)
    assert resume(other, code).status_code == 200
    assert other.get("/api/guest/room").json()["id"] == room["id"]


def test_resume_code_is_not_stored_in_plain_and_rejects_wrong_codes(client: TestClient, monkeypatch):
    guest(client)
    code = client.get("/api/guest/room").json()["resume_code"]
    from core.kv import get_store
    assert code.replace("-", "") not in str(get_store()._items)  # MemoryStore の中身。コードそのものは置かない
    assert resume(TestClient(app), "AAAA-BBBB-CCCC").status_code == 404
    assert resume(TestClient(app), "short").status_code == 404
    assert resume(TestClient(app), code, nickname="").status_code == 400

    # 当て推量は、接続元ごとに回数で止める
    monkeypatch.setattr(get_settings(), "guest_resume_attempts_per_hour", 3)
    stranger = TestClient(app)
    for _ in range(2):
        resume(stranger, "AAAA-BBBB-CCCC")
    assert resume(stranger, "AAAA-BBBB-CCCC").status_code in (404, 429)
    assert resume(stranger, code).status_code == 429


def test_resume_code_follows_room_and_guest_switch(client: TestClient, monkeypatch):
    guest(client)
    code = client.get("/api/guest/room").json()["resume_code"]
    # ルームを終えても、同じゲストの新しいルームに戻れる
    client.delete("/api/guest/room")
    new_room = client.get("/api/guest/room").json()
    assert resume(TestClient(app), code).status_code == 200
    # 新しいゲストを始めると、そのブラウザの前のコードは要らない（前のゲストのコードは期限まで残る）
    assert new_room["resume_code"] == code
    app_settings.update({"guest_enabled": False})
    assert resume(TestClient(app), code).status_code == 403


def test_privacy_page_states_retention_and_no_guest_personal_data(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "audit_log_retention_days", 30)
    page = client.get("/privacy").text
    assert "30 日たつと消します" in page and "__AUDIT_DAYS__" not in page
    assert "ゲストについて、個人を特定できる情報を預かりません" in page


def test_legal_pages_hide_contact_when_not_set(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_contact", "")
    for path in ("/terms", "/privacy"):
        page = client.get(path).text
        assert "お問い合わせ" not in page and "__CONTACT__" not in page and "contact -->" not in page
    monkeypatch.setattr(get_settings(), "operator_contact", "https://gitlab.com/benizuki/kazayomi/-/issues")
    page = client.get("/privacy").text
    assert "お問い合わせ" in page and "gitlab.com/benizuki/kazayomi" in page and "contact -->" not in page
