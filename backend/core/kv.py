"""期限付きの一時データの置き場（Valkey）。

撮像トークンのように「数十秒だけ有効で、1 回使ったら消す」ものを置く。
期限切れの掃除を Valkey の TTL に任せられるのと、gunicorn の worker を
複数にしても共有できるため。VALKEY_URL が未設定なら、プロセス内の辞書で代用する。
"""
from __future__ import annotations

import threading
import time
from typing import Protocol


class KeyValueStore(Protocol):
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    def get(self, key: str) -> str | None: ...
    def pop(self, key: str) -> str | None:
        """取り出して消す。2 回目以降は None。トークンの使い回しを防ぐ。"""
        ...
    def incr(self, key: str, ttl_seconds: int) -> int:
        """数を 1 増やして返す。期限は最初に数えたときから（回数の制限に使う）。"""
        ...


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [key for key, (_, expires_at) in self._items.items() if expires_at <= now]
        for key in expired:
            del self._items[key]

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            now = time.monotonic()
            self._purge(now)
            self._items[key] = (value, now + ttl_seconds)

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge(time.monotonic())
            item = self._items.get(key)
            return item[0] if item else None

    def pop(self, key: str) -> str | None:
        with self._lock:
            self._purge(time.monotonic())
            item = self._items.pop(key, None)
            return item[0] if item else None

    def incr(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            now = time.monotonic()
            self._purge(now)
            value, expires_at = self._items.get(key, ("0", now + ttl_seconds))
            count = int(value) + 1
            self._items[key] = (str(count), expires_at)
            return count


class ValkeyStore:
    def __init__(self, url: str, prefix: str = "kazayomi:") -> None:
        import valkey

        self._client = valkey.Valkey.from_url(url, decode_responses=True)
        self._prefix = prefix

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(self._prefix + key, value, ex=ttl_seconds)

    def get(self, key: str) -> str | None:
        return self._client.get(self._prefix + key)

    def pop(self, key: str) -> str | None:
        # GETDEL は取り出しと削除を 1 命令で行うので、同時に 2 回使われても 1 回しか成功しない
        return self._client.getdel(self._prefix + key)

    def incr(self, key: str, ttl_seconds: int) -> int:
        name = self._prefix + key
        count = int(self._client.incr(name))
        if count == 1:
            self._client.expire(name, ttl_seconds)
        return count


_store: KeyValueStore | None = None


def init_store(valkey_url: str) -> KeyValueStore:
    global _store
    _store = ValkeyStore(valkey_url) if valkey_url else MemoryStore()
    return _store


def get_store() -> KeyValueStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def set_store(store: KeyValueStore) -> None:
    """テスト用の差し替え口。"""
    global _store
    _store = store
