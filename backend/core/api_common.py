"""api/ の各ルータで共通に使う小さなヘルパ。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from config.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST_DIR = (BACKEND_DIR.parent / "frontend" / "dist").resolve()


def _json_error(message: str, status_code: int) -> JSONResponse:
    """エラーレスポンスの形を 1 つに揃える。フロント側の分岐が減る。"""
    return JSONResponse(status_code=status_code, content={"error": message, "status_code": status_code})


async def _request_json(request: Request) -> dict:
    """リクエスト本文を dict として読む。

    Pydantic のモデルを使わずこの形にしているのは、部分更新を受けるエンドポイントで
    「未指定」と「null 指定」を区別したいため。
    """
    body = await request.body()
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON が不正です: {exc.msg}") from exc
    return payload if isinstance(payload, dict) else {}


async def read_upload(upload: UploadFile) -> bytes:
    """アップロードを上限付きで読む。上限を超えたら読み切る前に止める。"""
    limit = get_settings().max_upload_bytes
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"画像が大きすぎます（上限 {limit // (1024 * 1024)}MB）。")
    return data


def zip_response(buffer: BinaryIO, filename: str) -> StreamingResponse:
    def iterate():
        try:
            while chunk := buffer.read(1024 * 1024):
                yield chunk
        finally:
            buffer.close()

    # 日本語のファイル名は filename* で渡す。filename には ASCII の代替を入れる。
    disposition = f"attachment; filename=\"download.zip\"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(iterate(), media_type="application/zip", headers={"Content-Disposition": disposition})


def _frontend_index() -> FileResponse:
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="frontend のビルド成果物が見つかりません。frontend で npm run build を実行してください。",
        )
    return FileResponse(index_file)
