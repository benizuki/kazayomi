"""FastAPI エントリポイント。

ここではアプリの組み立てだけを行い、業務ロジックは api/ と domain/ に置く。
ミドルウェアとルータは登録順で挙動が変わるため、順番を崩さないこと。

ログインは Google（core/auth.py）。開発時だけ APP_ENV=local で省ける（core/dev_auth.py）。
ログインが要らないのは /healthz、ログイン画面と、Kazami が呼ぶもの（撮像のアップロードは撮像トークン、
端末の登録・認証は QR の登録トークンと端末の署名で守る）だけ。
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware

from api.albums_api import router as albums_router
from api.ayame_api import router as ayame_router
from api.captures_api import router as captures_router
from api.config_api import router as config_router
from api.devices_api import router as devices_router
from api.images_api import router as images_router
from api.groups_api import router as groups_router
from api.masters_api import router as masters_router
from api.me_api import router as me_router
from api.signaling_api import router as signaling_router
from config.settings import APP_VERSION, get_settings
from core import audit
from core.api_common import FRONTEND_DIST_DIR, _frontend_index, _json_error, origin_allowed
from core.auth import auth_router, current_principal, init_session
from core.blobstore import LocalBlobStore, S3BlobStore, init_blobstore
from core.db import init_db
from core.dev_auth import assert_safe_environment
from core.kv import init_store
from core.security_headers import SecurityHeadersMiddleware, set_connect_src_provider
from domain import devices, images, servers, users
from domain.access import ForbiddenError
from domain.captures import CaptureAuthError
from domain.devices import DeviceAuthError
from domain.common import NotFoundError

logger = logging.getLogger(__name__)

# APP_ENV=local（ログイン省略）のままクラウドで起動しようとしていないかを最初に確かめる。
# 警告ではなく例外にするのは、ログは見落とされるが起動失敗は必ず気付かれるため。
assert_safe_environment()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    _check_public_base_url(settings.public_base_url)
    init_db(settings.data_dir / "kazayomi.db")
    images.configure(images.ImageConfig(
        thumbnail_size=settings.thumbnail_size,
        max_upload_bytes=settings.max_upload_bytes,
    ))
    init_blobstore(_make_blobstore(settings))
    init_store(settings.valkey_url)
    audit.configure(settings.data_dir / "audit_logs.jsonl", retention_days=settings.audit_log_retention_days)
    created = users.ensure_bootstrap_admins(settings.bootstrap_admin_emails)
    if created:
        logger.warning("bootstrap admins created: %d", len(created))
    yield


def _check_public_base_url(url: str) -> None:
    """登録 QR に入れる URL。Kazami が読めない形なら、QR を出すときではなく起動の時点で止める。"""
    if not url:
        return
    try:
        devices.api_origin(url)
    except ValueError as exc:
        raise RuntimeError(f"PUBLIC_BASE_URL が正しくありません: {exc}") from exc


def _make_blobstore(settings):
    """画像の置き場。S3_ENDPOINT_URL があれば rustfs、無ければ DATA_DIR の下。"""
    if not settings.s3_endpoint_url:
        logger.warning("S3_ENDPOINT_URL is not set; storing images under %s", settings.data_dir)
        return LocalBlobStore(settings.data_dir)
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise RuntimeError("S3_ENDPOINT_URL を設定したときは、S3_ACCESS_KEY と S3_SECRET_KEY も設定してください。")
    store = S3BlobStore(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )
    store.ensure_bucket()
    return store


app = FastAPI(title="kazayomi", version=APP_VERSION, lifespan=lifespan)

# 1. セキュリティヘッダー。最初に登録すると、他のミドルウェアが返すエラー応答にも付く。
#    connect-src に Ayame のシグナリング（マスターのサーバの URL）を足す。
app.add_middleware(SecurityHeadersMiddleware)
set_connect_src_provider(servers.signaling_origins)

# 2. セッション。認証ルータより先に入れないと request.session が使えない。
init_session(app)


app.include_router(auth_router)


# 3. 状態を変える要求は、よそのサイトから送らせない（CSRF 対策。ログアウトの強制も含む）。ブラウザは POST などに必ず Origin を付ける。
#    Origin が無いのはブラウザでないもの（Kazami、Ayame の認証 Webhook）で、Cookie ではなく各自のトークンや接続元で守っている。
#    preflight（OPTIONS）は見ないので、開発時の Vite（CORS で許した Origin）からの要求はこれまでどおり通る
@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    origin = request.headers.get("origin")
    if (request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None
            and not origin_allowed(origin, request.headers.get("host", ""))):
        return _json_error("ほかのサイトからの操作は受け付けません。", 403)
    return await call_next(request)


# 4. CORS。同一オリジン配信なら実質不要だが、開発時の Vite から叩くために残す。
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. 業務ルータ
app.include_router(me_router)
app.include_router(config_router)
app.include_router(masters_router)
app.include_router(groups_router)
app.include_router(devices_router)
app.include_router(ayame_router)
app.include_router(signaling_router)
app.include_router(captures_router)
app.include_router(images_router)
app.include_router(albums_router)

def _error_message(detail: object) -> str:
    if isinstance(detail, dict):
        return str(detail.get("error", detail))
    return str(detail)


@app.exception_handler(HTTPException)
async def handle_http_exception(_: Request, exc: HTTPException):
    response = _json_error(_error_message(exc.detail), exc.status_code)
    if exc.status_code == 401:
        # 画面はこれを見てログイン画面へ移る
        response.headers["X-Login-Url"] = "/login"
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    logger.info("request validation failed: %s", exc.errors())
    return _json_error("入力の形式が正しくありません。画面を開き直してからやり直してください。", 422)


# domain 層は HTTP を知らないので、例外の種類でステータスを決める。
# ValueError のメッセージは利用者向けに書いてある前提。
@app.exception_handler(images.QuotaExceededError)
async def handle_quota_exceeded(_: Request, exc: images.QuotaExceededError):
    # 507 Insufficient Storage。Kazami と画面は、ほかの失敗と区別してそのまま理由を見せる
    return _json_error(str(exc), 507)


@app.exception_handler(ValueError)
async def handle_value_error(_: Request, exc: ValueError):
    return _json_error(str(exc), 400)


@app.exception_handler(NotFoundError)
async def handle_not_found(_: Request, exc: NotFoundError):
    return _json_error(str(exc), 404)


@app.exception_handler(ForbiddenError)
async def handle_forbidden(_: Request, exc: ForbiddenError):
    return _json_error(str(exc), 403)


@app.exception_handler(DeviceAuthError)
async def handle_device_auth(_: Request, exc: DeviceAuthError):
    return _json_error(str(exc), 401)


@app.exception_handler(CaptureAuthError)
async def handle_capture_auth(_: Request, exc: CaptureAuthError):
    return _json_error(str(exc), 401)


@app.exception_handler(Exception)
async def handle_exception(_: Request, exc: Exception):
    # 詳細はサーバログに残し、利用者にはスタックトレースを見せない。
    logger.exception("unexpected error")
    return _json_error(f"サーバーでエラーが起きました（{type(exc).__name__}）。時間をおいてやり直してください。", 500)


@app.get("/healthz")
def healthz():
    """死活監視用。"""
    return {"status": "ok"}


# 6. SPA フォールバック。全パスを受けるので、必ず最後に登録する。
@app.get("/{path:path}")
def spa_fallback(path: str, request: Request):
    # API 相当のパスに index.html を返すと、フロント側は JSON パース失敗になり
    # 原因が追いにくい。ここで明示的に 404 を返す。
    if path.startswith(("api/", "auth/", "healthz")):
        return _json_error("not found", 404)

    # ビルド成果物（JS・CSS・アイコン）はログイン画面より前にも要るので、そのまま返す
    asset_path = (FRONTEND_DIST_DIR / path).resolve()
    if path and asset_path.is_file() and asset_path.is_relative_to(FRONTEND_DIST_DIR):
        # assets/ の下は Vite が中身の版を名前に入れているので、長くキャッシュしてよい。
        # ほか（public/ から来る theme-init.js や画像）は名前が変わらないので、毎回確かめさせる
        # （Cloudflare などが古いものを持ち続けないように）
        immutable = path.startswith("assets/")
        cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return FileResponse(asset_path, headers={"Cache-Control": cache})
    if current_principal(request) is None:
        target = "/" + path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(url=f"/login?next={quote(target)}", status_code=302)
    return _frontend_index()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=True)
