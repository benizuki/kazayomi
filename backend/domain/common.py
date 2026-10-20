"""domain 層で共通に使う小さなヘルパ。FastAPI に依存させない。"""
from __future__ import annotations

import json
import unicodedata
import uuid
from datetime import datetime


def new_id() -> str:
    return uuid.uuid4().hex


def now_local() -> datetime:
    # 日付フォルダや日付での絞り込みは、利用者の感覚に合わせてサーバーのローカル日付で切る。
    # コンテナでは TZ=Asia/Tokyo を渡す。
    return datetime.now().astimezone()


def to_iso(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="milliseconds")


def parse_datetime(value: str | None) -> datetime:
    """ISO 8601 を読む。タイムゾーンが無い値はサーバーのローカル時刻とみなす。

    読めない値は撮像を失敗させるほどのことではないので、受信時刻で代用する。
    """
    if not value:
        return now_local()
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return now_local()
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone()


# タグの決まり（1 枚に 20 個まで、1 つ 50 文字まで）
MAX_TAGS = 20
MAX_TAG_LENGTH = 50


def tag_key(tag: str) -> str:
    """タグを比べるための形。全角・半角と大文字・小文字の違いを同じものとみなす（「ＮＧ」「ng」「NG」は同じ）。"""
    return unicodedata.normalize("NFKC", tag).strip().casefold()


def normalize_tags(tags: object, *, limit: int | None = MAX_TAGS) -> list[str]:
    """タグの並びを揃える。空と表記ゆれの重複を除き、元の順と最初の書き方を保つ。

    文字は NFKC にそろえ（全角英数字は半角に）、先頭の「#」は外す（画面では #タグ と表示するため）。
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        items = tags.split(",")
    elif isinstance(tags, (list, tuple)):
        items = [str(t) for t in tags]
    else:
        raise ValueError("タグの形式が正しくありません。文字列の一覧で指定してください。")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = unicodedata.normalize("NFKC", item).strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"タグ「{tag[:20]}…」が長すぎます。{MAX_TAG_LENGTH} 文字以内にしてください。")
        key = tag_key(tag)
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    if limit is not None and len(result) > limit:
        raise ValueError(f"タグは 1 枚に {limit} 個までです。")
    return result


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def require_text(value: object, label: str, *, max_length: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label}を入力してください。")
    if len(text) > max_length:
        raise ValueError(f"{label}は {max_length} 文字以内にしてください。")
    return text


def optional_text(value: object, label: str, *, max_length: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise ValueError(f"{label}は {max_length} 文字以内にしてください。")
    return text


class NotFoundError(LookupError):
    """対象が無い。api 層で 404 にする。"""
