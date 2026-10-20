"""画面が起動時に読む設定。"""
from __future__ import annotations

from fastapi import APIRouter

from config.settings import APP_VERSION, get_settings
from core.auth import Viewer

router = APIRouter()


@router.get("/api/config")
def api_config(viewer: Viewer):  # noqa: ARG001 - ログインの確認だけ
    settings = get_settings()
    return {
        "version": APP_VERSION,
        "capture_token_ttl_seconds": settings.capture_token_ttl_seconds,
    }
