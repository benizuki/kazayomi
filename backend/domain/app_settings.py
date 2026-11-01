"""アプリ全体の設定。環境変数ではなく、画面（マスター）から変えるもの。"""
from __future__ import annotations

import json
from typing import Any

from core.db import connect
from domain.common import now_local, to_iso

# マスター › グループで新しく作るグループに付ける容量の上限。None は無制限
DEFAULT_GROUP_QUOTA = "default_group_quota_bytes"
# まだ画面で決めていないときの値。誰でもグループを作れるので、はじめは小さめにしておく
INITIAL_GROUP_QUOTA_BYTES = 100 * 1024 * 1024


def _get(key: str, default: Any = None) -> Any:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(key: str, value: Any) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), to_iso(now_local())),
        )


def parse_quota(value: object) -> int | None:
    """容量の上限（バイト）。空・None は無制限。"""
    if value is None or value == "":
        return None
    try:
        quota = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("容量の上限は数で指定してください。") from exc
    if quota <= 0:
        raise ValueError("容量の上限は 0 より大きくしてください（無制限にするときは空にします）。")
    return quota


def default_group_quota() -> int | None:
    """画面で「無制限」にしたときは None が保存されているので、初期値には戻らない。"""
    return _get(DEFAULT_GROUP_QUOTA, INITIAL_GROUP_QUOTA_BYTES)


def flag(key: str) -> bool:
    """画面には出さない、内部の目印（ローカルの初期データを作ったか、など）。"""
    return bool(_get(key, False))


def set_flag(key: str) -> None:
    _set(key, True)


def get_all() -> dict[str, Any]:
    return {"default_group_quota_bytes": default_group_quota()}


def update(payload: dict[str, Any]) -> dict[str, Any]:
    if "default_group_quota_bytes" in payload:
        _set(DEFAULT_GROUP_QUOTA, parse_quota(payload["default_group_quota_bytes"]))
    return get_all()
