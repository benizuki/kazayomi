"""Google ログインとセッション。

設計の要点:
- Google の署名検証を通っただけでは通さない。ユーザーマスターに登録済みで、
  有効であることを必ず確認する（Google アカウントは誰でも持てる）。
- セッション（HttpOnly の Cookie）にはメールアドレスだけを持つ。ロールと所属グループは
  リクエストのたびにユーザーマスターから読み直す。無効化や権限の変更をすぐ効かせるため。
- セッションに OAuth クライアント ID の指紋を入れ、設定を変えたら古いセッションを無効にする。
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.requests import HTTPConnection
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from config.settings import get_settings
from core.api_common import _request_json
from core.audit import record_auth_login, record_operation
from core.dev_auth import dev_auth_enabled, dev_principal
from core.kv import get_store
from domain import app_settings, guest_rooms, memberships, users
from domain.access import Principal, permissions_for_role

auth_router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

# 認証イベントは 1 行 1 JSON で標準出力に出す。
auth_event_logger = logging.getLogger("app.auth")
if not auth_event_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    auth_event_logger.addHandler(_handler)
auth_event_logger.setLevel(logging.INFO)
auth_event_logger.propagate = False

_GOOGLE_CLIENT_ID_RE = re.compile(r"^[0-9]+-[a-z0-9-]+\.apps\.googleusercontent\.com$")
_DEV_SESSION_SECRET = "local-development-only-not-a-secret"
# Google で確かめてから、招待を受ける・グループを作るまでの猶予。過ぎたらもう一度サインインしてもらう
_ONBOARDING_WINDOW_SECONDS = 15 * 60


def init_session(app) -> None:
    """セッションミドルウェアを登録する。認証ルータより先に呼ぶこと。

    APP_SESSION_SECRET が無いまま本番で起動すると、その場で落とす。
    設定漏れのまま動いてしまうより、起動しないほうが気付ける。
    開発時（APP_ENV=local）だけは固定値で代用する（セッションを使わないため）。
    """
    secret = get_settings().session_secret
    if not secret:
        if not dev_auth_enabled():
            raise RuntimeError("APP_SESSION_SECRET が設定されていません。長いランダムな文字列を設定してください。")
        secret = _DEV_SESSION_SECRET
    # https で配信しているときは Secure Cookie にする（http の開発環境では付けない）
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax",
                       https_only=get_settings().session_https_only, max_age=60 * 60 * 12)


# ── OAuth クライアント ID ──────────────────────────────

def google_oauth_client_id() -> str:
    return get_settings().google_oauth_client_id


def _oauth_client_id_error(client_id: str) -> str:
    if not client_id:
        return "GOOGLE_OAUTH_CLIENT_ID が設定されていません。"
    if not _GOOGLE_CLIENT_ID_RE.fullmatch(client_id):
        return "GOOGLE_OAUTH_CLIENT_ID の形式が不正です。Google OAuth のウェブクライアント ID を設定してください。"
    return ""


def _fingerprint(client_id: str) -> str:
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


# ── 誰がリクエストしているか ───────────────────────────

def current_principal(request: HTTPConnection) -> Principal | None:
    """HTTP でも WebSocket（シグナリングの中継）でも同じセッションで判定する。"""
    if dev_auth_enabled():
        return dev_principal()
    session_user = request.session.get("user")
    if not isinstance(session_user, dict):
        # ログインが切れていても、ゲストの「続きから使う」Cookie があれば、同じゲストに戻す
        return _resume_guest(request)
    if session_user.get("guest"):
        # ゲスト（Google ログインなし）。マスター › 設定 でゲストを止めたら、次のリクエストから入れない
        if not session_user.get("gid") or not app_settings.guest_enabled():
            return None
        _keep_guest_cookie(request, session_user)
        return guest_principal(str(session_user["gid"]), str(session_user.get("name") or "ゲスト"))
    if not session_user.get("email"):
        return None
    client_id = google_oauth_client_id()
    stored = str(request.session.get("oauth_client_id_fingerprint") or "")
    if _oauth_client_id_error(client_id) or not hmac.compare_digest(stored, _fingerprint(client_id)):
        return None
    # ユーザーマスターを毎回読む。無効化された人は、次のリクエストから入れない
    return users.principal_for(str(session_user["email"]))


def guest_principal(guest_id: str, nickname: str) -> Principal:
    """ゲスト。ログイン画面でニックネームだけを入れて始めた人。使えるのは自分の一時的なルームだけ。

    guest_id はゲストを始めたときに作る乱数で、セッション（署名付きの Cookie）にだけ持つ。
    """
    return Principal(email="", name=nickname, role="user", permissions=permissions_for_role("user"),
                     group_ids=frozenset(), subject=f"guest:{guest_id}")


# ── ゲストの「続きから使う」Cookie ─────────────────────
# ログインのセッションは 12 時間で切れるが、ゲストのルームは最後に使ってから 24 時間残る。
# ブラウザを閉じたり、しばらくあいだが空いたりしても同じルームに戻れるように、ゲストの ID とニックネームを
# 署名付きの Cookie に入れ、ルームと同じ長さだけ持つ。JavaScript からは読めない（HttpOnly）。
# ルーム ID ではなくゲストの ID を入れるのは、ルーム ID だけで入れると、知っている人が誰でも入れてしまうため。
GUEST_COOKIE = "kazayomi_guest"


def _guest_serializer():
    from itsdangerous import URLSafeTimedSerializer

    secret = get_settings().session_secret or _DEV_SESSION_SECRET
    return URLSafeTimedSerializer(secret, salt="kazayomi-guest-resume")


def _read_guest_cookie(request: HTTPConnection) -> dict[str, str] | None:
    from itsdangerous import BadSignature

    raw = request.cookies.get(GUEST_COOKIE)
    if not raw:
        return None
    try:
        data = _guest_serializer().loads(raw, max_age=get_settings().guest_room_ttl_seconds)
    except BadSignature:
        return None
    if not isinstance(data, dict) or not data.get("gid"):
        return None
    return {"gid": str(data["gid"]), "name": str(data.get("name") or "ゲスト"), "code": str(data.get("code") or "")}


def _keep_guest_cookie(request: HTTPConnection, user: dict) -> None:
    """応答のときに「続きから使う」Cookie を出し直してもらう（使うたびに期限が延びる）。

    再開コードも入れておく。コードそのものはサーバに置かないので、本人に見せられるのはここからだけ。
    """
    request.state.guest_cookie = {"gid": str(user["gid"]), "name": str(user.get("name") or "ゲスト"),
                                  "code": str(user.get("code") or "")}


def guest_session(request: HTTPConnection) -> dict | None:
    """ゲストのセッション（gid・name・code）。guest_api が再開コードを見せるときに使う。"""
    user = request.session.get("user")
    return user if isinstance(user, dict) and user.get("guest") else None


def ensure_resume_code(request: Request, principal: Principal) -> str:
    """再開コードを返す。まだなければ（この機能より前に始めたゲスト）作る。"""
    user = guest_session(request)
    if user is None:
        return ""
    if not user.get("code"):
        user = {**user, "code": guest_rooms.new_resume_code()}
        guest_rooms.register_resume_code(principal, user["code"])
        request.session["user"] = user
    _keep_guest_cookie(request, user)
    return str(user["code"])


def _resume_guest(request: HTTPConnection) -> Principal | None:
    data = _read_guest_cookie(request)
    if data is None or not app_settings.guest_enabled():
        return None
    user = {"guest": True, **data}
    if request.scope.get("type") == "http":
        # ログインの状態も作り直しておく（次からは Cookie を読み直さずに済む）
        request.session["user"] = user
    _keep_guest_cookie(request, user)
    return guest_principal(data["gid"], data["name"])


def apply_guest_cookie(request: Request, response) -> None:
    """main.py のミドルウェアから呼ぶ。ゲストなら Cookie を出し直し、ログアウトなら消す。"""
    if getattr(request.state, "guest_logout", False):
        response.delete_cookie(GUEST_COOKIE, path="/")
        return
    data = getattr(request.state, "guest_cookie", None)
    if data:
        response.set_cookie(
            GUEST_COOKIE, _guest_serializer().dumps(data), max_age=get_settings().guest_room_ttl_seconds,
            path="/", httponly=True, samesite="lax", secure=get_settings().session_https_only,
        )


# ゲストが呼べる API。ほかの API（画像・アルバム・グループ・マスターなど）は、ここで一律に断る
# （ゲストは所属グループを持たないので domain 層でも何も見えないが、入口でも閉じておく）
GUEST_API_PREFIXES = ("/api/me", "/api/config", "/api/guest/")


def require_principal(request: Request) -> Principal:
    """未ログインなら 401。ログインが要る API の依存関係に入れる。"""
    principal = current_principal(request)
    if principal is None:
        if request.session.get("user"):
            request.session.clear()
        raise HTTPException(status_code=401, detail={"error": "ログインが必要です。画面を開き直してください。", "login_url": "/login"})
    if principal.is_guest and not request.url.path.startswith(GUEST_API_PREFIXES):
        raise HTTPException(status_code=403, detail="ゲストでは使えない機能です。グループに招待してもらうか、グループを作ってください。")
    if not principal.is_guest and request.url.path.startswith("/api/guest/"):
        raise HTTPException(status_code=403, detail="一時的なルームはゲストだけが使えます。")
    return principal


# api/ のルータでは引数に `viewer: Viewer` と書くと、ログイン中のユーザーが入る
Viewer = Annotated[Principal, Depends(require_principal)]


def auth_mode() -> str:
    """"dev-bypass" のとき、画面は常時バナーを出す。"""
    return "dev-bypass" if dev_auth_enabled() else "google"


# ── ログの補助 ────────────────────────────────────────

def client_ip(request: Request) -> str:
    # リバースプロキシ配下では X-Forwarded-For の先頭が実クライアント
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _user_id_hash(email: str) -> str | None:
    """アプリケーションログ用の識別子。生のメールを載せないための代替。"""
    normalized = str(email or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _log_google_login(request: Request, *, result: str, status_code: int, email: str = "",
                      role: str = "", failure_reason: str = "") -> None:
    payload = {
        "severity": "INFO" if result == "success" else "WARNING",
        "message": "Google login succeeded" if result == "success" else "Google login failed",
        "event": "auth.login",
        "provider": "google",
        "result": result,
        "status_code": status_code,
        "user_id_hash": _user_id_hash(email),
        "role": role,
        "reason": failure_reason,
        "remote_ip": client_ip(request),
        "user_agent": request.headers.get("user-agent", ""),
        "path": str(request.url.path),
    }
    # 監査ログ（閲覧は管理者だけ）には追跡のため生のメールを残す。標準出力には載せない
    record_auth_login({**payload, "email": email or None})
    auth_event_logger.info(json.dumps(payload, ensure_ascii=False))


# ── ログイン画面 ──────────────────────────────────────

def _safe_login_redirect(request: Request) -> str:
    """ログイン後の戻り先を検証する。

    "//evil.example.com" はスキーム相対 URL として外部に飛ぶため、
    "/" 始まりの確認だけでは足りない。オープンリダイレクトはフィッシングの踏み台になる。
    """
    target = str(request.query_params.get("next") or "/")
    return target if target.startswith("/") and not target.startswith("//") else "/"


@auth_router.get("/login")
async def login(request: Request):
    redirect_target = _safe_login_redirect(request)
    if current_principal(request):
        return RedirectResponse(url=redirect_target, status_code=302)
    client_id = google_oauth_client_id()
    config_error = _oauth_client_id_error(client_id)
    template = (TEMPLATES_DIR / "login.html").read_text(encoding="utf-8")
    # data 属性に入れるので HTML としてエスケープする（戻り先には利用者が渡した文字列が入るため）
    page = (
        template
        .replace("__GOOGLE_CLIENT_ID__", html.escape(client_id if not config_error else ""))
        .replace("__GOOGLE_OAUTH_CONFIG_ERROR__", html.escape(config_error))
        .replace("__LOGIN_REDIRECT__", html.escape(redirect_target))
        .replace("__GUEST_ENABLED__", "true" if app_settings.guest_enabled() else "false")
        .replace("__LOGIN_JS_VERSION__", asset_version("login.js"))
        .replace("__TERMS_VERSION__", html.escape(guest_rooms.TERMS_VERSION))
    )
    return HTMLResponse(page)


# ログイン画面のスクリプトとスタイル。Cloudflare などが拡張子を見て長くキャッシュすると、更新したあとも
# 古いものが返り、画面が動かなくなる（ゲストの欄が出ないなど）。毎回確かめさせ、URL にも中身の版を付ける
_NO_STORE_CACHE = {"Cache-Control": "no-cache"}


def asset_version(name: str) -> str:
    """ファイルの中身から作る版（中身が変われば URL も変わる）。"""
    return hashlib.sha256((TEMPLATES_DIR / name).read_bytes()).hexdigest()[:12]


@auth_router.get("/auth/login.js")
def login_script():
    return FileResponse(TEMPLATES_DIR / "login.js", media_type="text/javascript", headers=_NO_STORE_CACHE)


@auth_router.get("/auth/legal.css")
def legal_stylesheet():
    return FileResponse(TEMPLATES_DIR / "legal.css", media_type="text/css", headers=_NO_STORE_CACHE)


def _verify_google_credential(credential: str) -> dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import id_token

    client_id = google_oauth_client_id()
    config_error = _oauth_client_id_error(client_id)
    if config_error:
        raise HTTPException(status_code=500, detail=config_error)
    try:
        # 第 3 引数の client_id で aud を検証する。省くと、別アプリ向けのトークンを受け入れてしまう
        user_info = id_token.verify_oauth2_token(credential, GoogleAuthRequest(), client_id)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Google 認証トークンの検証に失敗しました。") from exc
    if user_info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Google 認証トークンの発行元が不正です。")
    if not user_info.get("email_verified", False):
        # 未確認のメールを許すと、他人のメールを騙るアカウントを通してしまう
        raise HTTPException(status_code=403, detail="メールアドレスが未確認のためログインできません。")
    return user_info


@auth_router.post("/auth/google")
async def auth_google(request: Request):
    try:
        payload = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        payload = None
    credential = str(payload.get("credential") or "") if isinstance(payload, dict) else ""
    if not credential.strip():
        _log_google_login(request, result="failure", status_code=400, failure_reason="missing_credential")
        raise HTTPException(status_code=400, detail="credential が必要です。")
    try:
        user_info = _verify_google_credential(credential)
    except HTTPException as exc:
        _log_google_login(request, result="failure", status_code=exc.status_code, failure_reason=str(exc.detail))
        raise

    email = users.normalize_email(user_info.get("email", ""))
    display_name = str(user_info.get("name") or email)
    # ここが認可の入口。Google の検証を通っただけでは通さない
    principal = users.principal_for(email)

    if principal is None:
        request.session.clear()
        if users.find_by_email(email) is not None:
            _log_google_login(request, result="failure", status_code=403, email=email, failure_reason="user_disabled")
            raise HTTPException(status_code=403, detail=f"{email} は利用が止められています。管理者に確認してください。")
        invitations = memberships.invitations_for(email)
        if not invitations:
            # 登録されていない人のメールアドレスは、記録に残さない
            _log_google_login(request, result="failure", status_code=403, failure_reason="not_registered")
            hint = "ゲストとして試すときは、ログイン画面の「ゲストとして試す」から始めてください。" if app_settings.guest_enabled() else ""
            raise HTTPException(status_code=403, detail=f"{email} は登録されていません。グループの管理者に招待を依頼してください。{hint}")
        # 届いている招待に参加してもらう。招待は、このメールアドレスでだけ扱う（画面から送られたメールアドレスは使わない）。
        # セッションは署名付きの Cookie なので、サーバには残らない
        request.session["onboarding"] = {"email": email, "name": display_name, "verified_at": int(time.time())}
        return JSONResponse(status_code=403, content={
            "error": f"{email} はまだ登録されていません。",
            "status_code": 403,
            "onboarding": {
                "email": email,
                "name": display_name,
                "invitations": [_invitation_view(i) for i in invitations],
            },
        })

    _start_session(request, email, display_name, picture=user_info.get("picture", ""))
    _log_google_login(request, result="success", status_code=200, email=email, role=principal.role)
    return JSONResponse({"ok": True})


def _invitation_view(invitation: dict[str, Any]) -> dict[str, Any]:
    """ログイン画面に出す招待。招待した人のメールアドレスは出さない（本人に要るのはグループと役割）。"""
    return {"id": invitation["id"], "group_name": invitation["group_name"], "role": invitation["role"],
            "expires_at": invitation["expires_at"]}


def _onboarding_identity(request: Request) -> dict[str, str]:
    """Google で確かめたばかりの、まだ登録されていない人。なければ 401。"""
    identity = request.session.get("onboarding")
    if not isinstance(identity, dict) or not identity.get("email"):
        raise HTTPException(status_code=401, detail="もう一度 Google でサインインしてください。")
    if int(time.time()) - int(identity.get("verified_at") or 0) > _ONBOARDING_WINDOW_SECONDS:
        request.session.pop("onboarding", None)
        raise HTTPException(status_code=401, detail="時間がたったため、もう一度 Google でサインインしてください。")
    return identity


async def _onboarding_payload(request: Request) -> dict[str, Any]:
    # 状態を変えるので JSON に限る（フォームの POST では送れないので、ほかのサイトから送らせられない）
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON で送ってください。")
    return await _request_json(request)


def _start_session(request: Request, email: str, name: str, *, picture: str = "") -> None:
    # セッション固定を避けるため、ログインのたびに作り直す
    request.session.clear()
    request.session["user"] = {"email": email, "name": name, "picture": picture}
    request.session["oauth_client_id_fingerprint"] = _fingerprint(google_oauth_client_id())
    users.record_login(email, name)


# ── ゲスト ───────────────────────────────────────
_GUEST_NICKNAME_MAX = 30


def _guest_nickname(payload: dict) -> str:
    nickname = " ".join(str(payload.get("nickname") or "").split())
    if not nickname:
        raise HTTPException(status_code=400, detail="ニックネームを入力してください（本名でなくてかまいません）。")
    if len(nickname) > _GUEST_NICKNAME_MAX:
        raise HTTPException(status_code=400, detail=f"ニックネームは {_GUEST_NICKNAME_MAX} 文字以内にしてください。")
    return nickname


async def _guest_payload(request: Request) -> dict:
    if not app_settings.guest_enabled():
        raise HTTPException(status_code=403, detail="ゲストでの利用は受け付けていません。グループの管理者に招待を依頼してください。")
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON で送ってください。")
    return await _request_json(request)


def _start_guest(request: Request, user: dict) -> None:
    # セッション固定を避けるため、作り直す
    request.session.clear()
    request.session["user"] = user
    _keep_guest_cookie(request, user)


def _client_key(request: Request) -> str:
    """回数の制限に使う接続元。IP アドレスはそのまま置かず、鍵付きのハッシュにする。"""
    secret = (get_settings().session_secret or _DEV_SESSION_SECRET).encode()
    return hmac.new(secret, client_ip(request).encode(), hashlib.sha256).hexdigest()[:32]


@auth_router.post("/auth/guest")
async def auth_start_guest(request: Request):
    """ログイン画面の「ゲストとして試す」。Google ログインは使わず、ニックネームと利用規約への同意だけで始める。

    サーバには何も保存しない。ゲストの ID とニックネームはセッション（署名付きの Cookie）にだけ持つ。
    アカウントで乱用を止められないので、同じ接続元から 1 時間に始められる数を制限する。
    """
    payload = await _guest_payload(request)
    nickname = _guest_nickname(payload)
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="利用規約とプライバシーポリシーへの同意が必要です。")
    if get_store().incr(f"guest-start:{_client_key(request)}", 3600) > get_settings().guest_starts_per_hour:
        raise HTTPException(status_code=429, detail="ゲストを続けて始めすぎています。しばらく待ってからやり直してください。")

    principal = guest_principal(secrets.token_urlsafe(16), nickname)
    guest_rooms.consent(principal, payload.get("version"))
    code = guest_rooms.new_resume_code()
    guest_rooms.register_resume_code(principal, code)
    _start_guest(request, {"guest": True, "gid": principal.subject.removeprefix("guest:"), "name": nickname, "code": code})
    # ゲストの記録には、ニックネームも残さない
    record_auth_login({"result": "success", "status_code": 200, "email": None, "role": "guest", "message": "guest start",
                       "remote_ip": client_ip(request), "user_agent": request.headers.get("user-agent", "")})
    return JSONResponse({"ok": True, "guest": True})


@auth_router.post("/auth/onboarding/accept")
async def auth_accept_invitation(request: Request):
    """ログイン画面で招待を受けて参加する。そのままログインした状態になる。"""
    identity = _onboarding_identity(request)
    payload = await _onboarding_payload(request)
    result = memberships.accept_invitation(str(payload.get("invitation_id") or ""), identity["email"],
                                           user_name=str(payload.get("name") or identity["name"]))
    invitation = result["invitation"]
    record_operation(actor_email=identity["email"], event="invitation.accept", target=invitation["group_id"],
                     detail=f"role={invitation['role']} invited_by={invitation['invited_by']}")
    _start_session(request, identity["email"], result["user"]["name"])
    _log_google_login(request, result="success", status_code=200, email=identity["email"], role=result["user"]["role"])
    return {"ok": True, "group_name": invitation["group_name"]}


@auth_router.post("/auth/guest/resume")
async def auth_resume_guest(request: Request):
    """再開コードで、前のゲスト（同じルーム）に戻る。ログアウトしたあとや、別のブラウザから使う。

    ニックネームはサーバに置いていないので、入れ直してもらう。コードの当て推量を防ぐため、
    同じ接続元から 1 時間に試せる回数を制限する。
    """
    payload = await _guest_payload(request)
    nickname = _guest_nickname(payload)
    if get_store().incr(f"guest-resume:{_client_key(request)}", 3600) > get_settings().guest_resume_attempts_per_hour:
        raise HTTPException(status_code=429, detail="再開コードを続けて試しすぎています。しばらく待ってからやり直してください。")
    gid = guest_rooms.resolve_resume_code(payload.get("code"))
    if gid is None:
        raise HTTPException(status_code=404, detail="再開コードが見つかりません。コードを確かめてください（使わないまま 24 時間たつと消えます）。")
    code = guest_rooms.normalize_resume_code(payload.get("code"))
    code = "-".join(code[i:i + 4] for i in range(0, len(code), 4))
    _start_guest(request, {"guest": True, "gid": gid, "name": nickname, "code": code})
    record_auth_login({"result": "success", "status_code": 200, "email": None, "role": "guest", "message": "guest resume",
                       "remote_ip": client_ip(request), "user_agent": request.headers.get("user-agent", "")})
    return JSONResponse({"ok": True, "guest": True})


@auth_router.post("/logout")
async def logout(request: Request):
    # 個別キーの削除は消し漏れる。丸ごと消す。状態を変えるので GET では受けない
    request.session.clear()
    # ゲストの「続きから使う」Cookie も消す（共用の PC で、次の人が前の人のルームに入らないように）
    request.state.guest_logout = True
    return JSONResponse({"ok": True, "login_url": "/" if dev_auth_enabled() else "/login"})


def session_picture(request: Request) -> str:
    user = request.session.get("user")
    return str(user.get("picture") or "") if isinstance(user, dict) else ""
