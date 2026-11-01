"""開発中だけ Google ログインを省くための仕組み。

ローカルで画面を触るたびに Google の同意画面を通すのは、開発を確実に遅くする。
OAuth クライアント ID をまだ発行していない段階でも画面を作れるようにしたい。

**ただしこれは認証を丸ごと外す機能なので、本番で有効になったら終わりになる。**
そのため次の段で守っている。1 つでも通らなければ有効にならない。

  1. 既定は無効。`APP_ENV` が未設定なら production 扱いにする（fail closed）
  2. クラウド上の実行を検出したら**起動を止める**（設定ミスに気付かせる）
  3. 有効なときは起動ログに警告を出し、`/api/me` に `auth_mode` を載せる。
     画面上部に常時バナーが出るので、気付かずに使い続けることはできない
  4. compose.yaml には local を書かない。既定は空（production 扱い）で、local にするのは
     この PC の中だけで試すときの .env（compose.yaml と同じ場所）か backend/.env だけ
"""
from __future__ import annotations

import logging
import os

from domain.access import Permissions, Principal, permissions_for_role

logger = logging.getLogger(__name__)

# 環境を示す唯一の変数。local のときだけ開発用の抜け道が開く。
# **未設定は production 扱い**。「設定し忘れたら安全側」に倒すため。
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()

# クラウド上で動いていることを示す環境変数。
# プラットフォームが自動で入れるので、アプリ側の設定ミスでは消えない。
_CLOUD_MARKERS = (
    "K_SERVICE",              # Cloud Run
    "K_REVISION",             # Cloud Run
    "GAE_ENV",                # App Engine
    "KUBERNETES_SERVICE_HOST",  # k8s / k3s
    "FUNCTION_TARGET",        # Cloud Functions
)


def dev_auth_enabled() -> bool:
    """開発用の認証スキップが有効か。"""
    return APP_ENV == "local"


def assert_safe_environment() -> None:
    """クラウド上で APP_ENV=local になっていたら起動を止める。

    警告ログではなく例外にするのは、ログは見落とされるが、起動失敗は必ず気付かれるため。
    """
    if not dev_auth_enabled():
        return

    detected = [name for name in _CLOUD_MARKERS if os.getenv(name)]
    if detected:
        raise RuntimeError(
            "APP_ENV=local のままクラウド上で起動しようとしています "
            f"（検出: {', '.join(detected)}）。\n"
            "認証が無効になるため起動を中止しました。\n"
            "APP_ENV を削除するか production にしてください。"
            "APP_ENV=local を書いてよいのはローカルの backend/.env だけです。"
        )

    logger.warning(
        "\n"
        "  ============================================================\n"
        "   APP_ENV=local: Google ログインを省略しています\n"
        "   全リクエストが %s (%s) として扱われます\n"
        "   この状態で公開しないこと\n"
        "  ============================================================",
        dev_user()["email"],
        dev_role(),
    )


def dev_user() -> dict[str, str]:
    """開発時に「ログインしている人」として扱うユーザー。"""
    email = os.getenv("DEV_USER_EMAIL", "dev@example.com").strip().lower()
    name = os.getenv("DEV_USER_NAME", "開発ユーザー").strip()
    return {"email": email, "name": name, "picture": ""}


def dev_role() -> str:
    """開発ユーザーのロール。

    **`power` や `user` に切り替えて確認すること。**
    admin のままだと、権限で隠れるはずの画面が全部見えてしまい、
    「一般ユーザーには操作できない」を作り込めているか確認できない。
    """
    return os.getenv("DEV_USER_ROLE", "admin").strip() or "admin"


def dev_permissions() -> Permissions:
    return permissions_for_role(dev_role())


def dev_principal() -> Principal:
    """開発ユーザーを Principal にする。

    DEV_USER_EMAIL のユーザーがユーザーマスターにいれば、そのロールと所属グループを使う
    （グループでの絞り込みを確かめたいときは、そうする）。
    いなければ DEV_USER_ROLE のロールで、全グループを見られる人として扱う。
    """
    from domain import users

    user = dev_user()
    principal = users.principal_for(user["email"])
    if principal is not None:
        return principal
    return Principal(email=user["email"], name=user["name"], role=dev_role(),
                     permissions=dev_permissions(), group_ids=None)
