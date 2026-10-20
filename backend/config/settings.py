"""環境変数をここ 1 箇所に集約する。

os.getenv をアプリ各所に書くと、必要な設定の全体像が誰にも分からなくなり、
デプロイのたびに設定漏れで落ちる。新しい環境変数を足したら、
必ず .env.sample と compose.yaml も同じ変更の中で更新すること。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_BACKEND_DIR = Path(__file__).resolve().parents[1]

APP_VERSION = "0.1.0"


def _env_flag(*keys: str, default: bool = False) -> bool:
    """真偽値の環境変数。複数キーを渡すと、先に見つかったものを使う。"""
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def _env_str(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        normalized = value.strip()
        if normalized:
            return normalized
    return default


def _env_int(*keys: str, default: int = 0) -> int:
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        try:
            return int(value.strip())
        except ValueError:
            continue
    return default


def _env_csv(*keys: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        items = tuple(item.strip() for item in value.split(",") if item.strip())
        if items:
            return items
    return default


class Settings:
    # ── ゲスト ──
    # ログイン画面で「ゲストとして試す」を選んだ人は、ニックネームだけで一時的なルームを 1 つ使える
    # （マスター › 設定 で止められる）。ゲストのルームの期限（最後に使ってからの秒数）
    guest_room_ttl_seconds: int = _env_int("GUEST_ROOM_TTL_SECONDS", default=24 * 60 * 60)
    # 同じ接続元（IP アドレス）から 1 時間に始められるゲストの数。Google ログインがないので、乱用はこれで抑える
    guest_starts_per_hour: int = _env_int("GUEST_STARTS_PER_HOUR", default=10)
    # 同じ接続元から 1 時間に試せる再開コードの数（当て推量を防ぐ）
    guest_resume_attempts_per_hour: int = _env_int("GUEST_RESUME_ATTEMPTS_PER_HOUR", default=20)
    # 利用規約・プライバシーポリシーに出す運営者の表示と問い合わせ先
    operator_name: str = _env_str("OPERATOR_NAME", default="Benizuki")
    # 問い合わせ先。空なら、規約とポリシーに「お問い合わせ」の節を出さない（個人情報を預からないので必須ではない）
    operator_contact: str = _env_str("OPERATOR_CONTACT")

    # ── ログイン ──
    # セッション Cookie の署名鍵。本番では必須（main.py の起動時に確認する）。変えると全員ログアウトになる
    session_secret: str = _env_str("APP_SESSION_SECRET")
    # https で配信しているときは true にして、Cookie を https でだけ送らせる
    session_https_only: bool = _env_flag("SESSION_HTTPS_ONLY", default=False)
    google_oauth_client_id: str = _env_str("GOOGLE_OAUTH_CLIENT_ID")
    # 起動時に管理者として登録する人（いなければ）。ユーザーマスターが空だと誰も入れないため
    bootstrap_admin_emails: tuple[str, ...] = _env_csv("BOOTSTRAP_ADMIN_EMAILS")

    allowed_origins: tuple[str, ...] = _env_csv(
        "CORS_ALLOWED_ORIGINS",
        default=("http://127.0.0.1:8080", "http://localhost:5173"),
    )

    data_dir: Path = Path(_env_str("DATA_DIR", default=str(_BACKEND_DIR / "data")))
    # 監査ログ（ログインの成否・IP アドレス・操作）を残す日数。過ぎたものは消す。0 なら消さない
    audit_log_retention_days: int = _env_int("AUDIT_LOG_RETENTION_DAYS", default=90)

    # Ayame の認証 Webhook（/api/ayame/authn）を呼んでよい接続元（IP か CIDR、カンマ区切り）。
    # 既定は自分自身だけ。Ayame は kazayomi と同じネットワーク名前空間で動かし、127.0.0.1 で呼ばせる
    ayame_webhook_allowed_ips: tuple[str, ...] = _env_csv("AYAME_WEBHOOK_ALLOWED_IPS", default=("127.0.0.1", "::1"))
    # 追加で ?key= の一致も求めるときに設定する（任意）
    ayame_webhook_secret: str = _env_str("AYAME_WEBHOOK_SECRET")

    # 撮像トークン（Kazami がアップロードに使う）を置く Valkey。
    # 未設定ならプロセス内のメモリに置く。worker が 1 つの開発時とテスト向け。
    valkey_url: str = _env_str("VALKEY_URL")
    capture_token_ttl_seconds: int = _env_int("CAPTURE_TOKEN_TTL_SECONDS", default=60)

    # ── デバイス（Kazami）──
    # 端末のアクセストークンの有効期間。切れたら端末は自動で認証し直す
    device_token_ttl_seconds: int = _env_int("DEVICE_TOKEN_TTL_SECONDS", default=12 * 60 * 60)
    # 登録 QR に入れる kazayomi の URL（Kazami から届くもの）。空なら画面を開いている URL を候補にする
    public_base_url: str = _env_str("PUBLIC_BASE_URL")

    # ── 画像の置き場（rustfs / S3 互換）──
    # S3_ENDPOINT_URL を設定すると rustfs に置く。未設定なら DATA_DIR の下（テストと、手早く試すとき用）
    s3_endpoint_url: str = _env_str("S3_ENDPOINT_URL")
    s3_access_key: str = _env_str("S3_ACCESS_KEY")
    s3_secret_key: str = _env_str("S3_SECRET_KEY")
    s3_bucket: str = _env_str("S3_BUCKET", default="kazayomi")
    s3_region: str = _env_str("S3_REGION", default="us-east-1")

    # 1 枚あたりの上限。Kazami の JPEG（1920x1080）は 1MB 前後なので十分に余裕を持たせる。
    max_upload_bytes: int = _env_int("MAX_UPLOAD_BYTES", default=30 * 1024 * 1024)
    thumbnail_size: int = _env_int("THUMBNAIL_SIZE", default=320)


@lru_cache
def get_settings() -> Settings:
    """設定は 1 度だけ読む。プロセス起動後の環境変数変更は反映されない。"""
    return Settings()
