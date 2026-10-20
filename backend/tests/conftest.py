"""テスト共通の準備。

保存先は必ず一時ディレクトリに向ける。settings はインポート時に環境変数を読むので、
アプリのモジュールを読み込む前に DATA_DIR を差し替える。
"""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kazayomi-test-")
os.environ["VALKEY_URL"] = ""
# backend/.env に rustfs の設定があっても、テストでは使わない（ローカルの一時ディレクトリに置く）
os.environ["S3_ENDPOINT_URL"] = ""
os.environ["APP_SESSION_SECRET"] = "test-session-secret"
# backend/.env に APP_ENV=local があっても、テストではログインを省かない（dotenv は既にある値を上書きしない）
os.environ["APP_ENV"] = "test"

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from core import audit, blobstore, db, kv  # noqa: E402
from domain import rooms, groups, images  # noqa: E402
from domain.access import Principal, permissions_for_role  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path):
    """テストごとに空の DB と保存先を用意する。"""
    db.init_db(tmp_path / "kazayomi.db")
    images.configure(images.ImageConfig(thumbnail_size=64, max_upload_bytes=5 * 1024 * 1024))
    blobstore.init_blobstore(blobstore.LocalBlobStore(tmp_path))
    kv.set_store(kv.MemoryStore())
    audit.configure(tmp_path / "audit_logs.jsonl")
    yield tmp_path


def principal(role: str = "admin", groups_: set[str] | None = None, email: str = "tester@example.com") -> Principal:
    """テスト用のログインユーザー。groups_ を渡さず admin なら全グループ。"""
    perms = permissions_for_role(role)
    group_ids = None if (groups_ is None and perms["can_manage_users"]) else frozenset(groups_ or set())
    return Principal(email=email, name="テスト", role=role, permissions=perms, group_ids=group_ids)


def make_group(group_id: str, name: str | None = None) -> dict:
    return groups.create_group({"id": group_id, "name": name or group_id})


def make_room(name: str = "ライン1", ayame_room_id: str = "line-1", group_id: str = "default") -> dict:
    return rooms.create_room({"name": name, "ayame_room_id": ayame_room_id, "group_id": group_id})


def make_jpeg(width: int = 80, height: int = 60, color: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "JPEG")
    return buffer.getvalue()
