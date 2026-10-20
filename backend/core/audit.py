"""監査ログ。

「誰が」「いつ」「何をしたか」を JSONL に追記する。
アプリケーションログ（標準出力）と分けているのは、保管期間と閲覧権限が
別物だから。監査ログは追跡のために生のメールアドレスを持つ代わりに、
閲覧を can_manage_users 権限に限定する。

ファイルはサイズでローテートする。放置すると読み出しが重くなり、
ディスクも食う。あわせて、保存期間（既定 90 日）を過ぎた記録は消す。
IP アドレスなどを「不正利用への対応に要る間だけ」持つため（プライバシーポリシーにもそう書いている）。
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_MAX_LOGS = 1000
# ファイルが読めない環境（権限、マウント忘れ）でも直近の分は見られるよう、
# メモリ上にも保持しておく。
_LOGS: deque[dict[str, Any]] = deque(maxlen=_MAX_LOGS)
_LOCK = threading.Lock()

# 置き場は起動時に configure() で DATA_DIR の下に決める（コンテナではボリュームに残すため）
_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "audit_logs.jsonl"
_LOG_MAX_BYTES = int(os.getenv("AUTH_AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
_LOG_BACKUP_COUNT = int(os.getenv("AUTH_AUDIT_LOG_BACKUP_COUNT", "5"))


_RETENTION_DAYS = 90
# 古い記録を消すのは、起動したときと、そのあと 1 時間に 1 回まで（書くたびにファイルを読み直さないように）
_PURGE_INTERVAL_SECONDS = 3600
_last_purge = 0.0


def configure(path: Path, retention_days: int = 90) -> None:
    global _LOG_PATH, _RETENTION_DAYS
    _LOG_PATH = path
    _RETENTION_DAYS = retention_days
    purge_expired()


@contextmanager
def _file_lock():
    """gunicorn の worker どうしで、書き足しと古い記録の削除がぶつからないようにする。"""
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_PATH.with_name(_LOG_PATH.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def purge_expired(now: datetime | None = None) -> int:
    """保存期間を過ぎた記録を消す。消した件数を返す。0 日以下なら消さない。"""
    global _last_purge
    if _RETENTION_DAYS <= 0:
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=_RETENTION_DAYS)

    def keep(entry: dict[str, Any]) -> bool:
        stamp = _parse_time(entry.get("timestamp"))
        return stamp is not None and stamp >= cutoff

    removed = 0
    with _LOCK:
        _last_purge = time.monotonic()
        kept = [entry for entry in _LOGS if keep(entry)]
        _LOGS.clear()
        _LOGS.extend(kept)
        try:
            with _file_lock():
                for path in [_LOG_PATH] + [_rotated_path(i) for i in range(1, _LOG_BACKUP_COUNT + 1)]:
                    if not path.is_file():
                        continue
                    lines = path.read_text(encoding="utf-8").splitlines()
                    survivors = []
                    for line in lines:
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(entry, dict) and keep(entry):
                            survivors.append(line)
                    removed += len(lines) - len(survivors)
                    if len(survivors) == len(lines):
                        continue
                    if not survivors:
                        path.unlink()
                        continue
                    tmp = path.with_name(path.name + ".tmp")
                    tmp.write_text("\n".join(survivors) + "\n", encoding="utf-8")
                    tmp.replace(path)
        except Exception:
            # 消せなくても本処理は止めない（次の機会にまた消す）
            return removed
    return removed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rotated_path(index: int) -> Path:
    return _LOG_PATH.with_name(f"{_LOG_PATH.name}.{index}")


def _rotate_logs_if_needed() -> None:
    if _LOG_MAX_BYTES <= 0 or _LOG_BACKUP_COUNT <= 0:
        return
    if not _LOG_PATH.exists() or _LOG_PATH.stat().st_size < _LOG_MAX_BYTES:
        return

    oldest = _rotated_path(_LOG_BACKUP_COUNT)
    if oldest.exists():
        oldest.unlink()
    for index in range(_LOG_BACKUP_COUNT - 1, 0, -1):
        src = _rotated_path(index)
        if src.exists():
            src.replace(_rotated_path(index + 1))
    _LOG_PATH.replace(_rotated_path(1))


def _append_log(entry: dict[str, Any]) -> None:
    if time.monotonic() - _last_purge > _PURGE_INTERVAL_SECONDS:
        purge_expired()
    with _LOCK:
        _LOGS.appendleft(entry)
        try:
            with _file_lock():
                _rotate_logs_if_needed()
                with _LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
                    f.write("\n")
        except Exception:
            # 監査ログの永続化に失敗しても本処理は止めない。
            # ログが書けないことより、業務が止まるほうが利用者への影響が大きい。
            return


def record_auth_login(payload: dict[str, Any]) -> None:
    """ログインの成否を記録する。

    失敗は理由まで残す。「同じ IP から未登録メールで失敗し続けている」
    のようなパターンを後から見つけられるようにするため。
    """
    _append_log({
        "timestamp": _now_iso(),
        "category": "authentication",
        "event": "auth.login",
        "outcome": "success" if payload.get("result") == "success" else "failure",
        "email": payload.get("email"),
        "role": payload.get("role"),
        "status_code": payload.get("status_code"),
        "detail": payload.get("reason") or payload.get("message"),
        "source_ip": payload.get("remote_ip"),
        "user_agent": payload.get("user_agent"),
        "method": "POST",
        "path": payload.get("path") or "/auth/google",
    })


def record_operation(
    *,
    actor_email: str,
    event: str,
    target: str,
    detail: str = "",
    category: str = "authorization",
    outcome: str = "success",
) -> None:
    """マスターや権限を変える操作と、消すなどの重要な操作を記録する。

    「いつ誰にこの権限が付いたのか」「消したのは誰か」に答えられるようにするため。
    category は権限・マスターの変更が authorization、業務の操作が operation。
    """
    _append_log({
        "timestamp": _now_iso(),
        "category": category,
        "event": event,
        "outcome": outcome,
        "email": actor_email,
        "status_code": 200 if outcome == "success" else 400,
        "detail": detail,
        "target": target,
    })


def list_auth_audit_logs(limit: int = 500) -> list[dict[str, Any]]:
    """新しい順に返す。閲覧は can_manage_users に限定すること。"""
    safe_limit = max(1, min(limit, _MAX_LOGS))
    try:
        entries: list[dict[str, Any]] = []
        paths = [_LOG_PATH] + [_rotated_path(i) for i in range(1, _LOG_BACKUP_COUNT + 1)]
        for path in paths:
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            # ファイル全体を読まず末尾側だけを見る。壊れた行は黙って飛ばす。
            for line in reversed(lines[-safe_limit * 2:]):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    entries.append(item)
                if len(entries) >= safe_limit:
                    return entries
        if entries:
            return entries
    except Exception:
        pass
    # ファイルが読めないときはメモリ上の分を返す。
    with _LOCK:
        return list(_LOGS)[:safe_limit]
