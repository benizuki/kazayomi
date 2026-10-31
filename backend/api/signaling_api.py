"""Ayame のシグナリングを kazayomi 経由で中継する（ブラウザ用）。

ブラウザは Ayame（例: ws://192.168.1.10:3000）に直接つながず、画面と同じ Origin の
/api/rooms/{id}/signaling につなぐ。理由:
- Chrome の Local Network Access により、http://<IP> で開いた画面（安全でないコンテキスト）からは、
  別の Origin（別のポートの Ayame）への WebSocket が止められる。同じ Origin なら止められない
- ブラウザから Ayame に届かなくてもよくなる（届く必要があるのは kazayomi と Kazami だけ）
- ルームを見られる人だけが、そのルームのサーバにつながる

中継するだけで、中身（register・offer・answer など）には手を加えない。入室の可否は、これまでどおり
Ayame の認証 Webhook が入室チケットで決める。Kazami は今までどおり Ayame に直接つなぐ。
"""
from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from core.api_common import origin_allowed
from core.auth import current_principal
from domain import rooms
from domain.common import NotFoundError

router = APIRouter()
logger = logging.getLogger(__name__)

# WebSocket の close コード。画面はこれを見て、理由を出す
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_NOT_FOUND = 4404
_CLOSE_UPSTREAM_UNREACHABLE = 4502
_CLOSE_NO_SERVER = 4503
_CLOSE_FORBIDDEN_ORIGIN = 4403


def _origin_allowed(websocket: WebSocket) -> bool:
    """よそのサイトから、ログイン中の人の Cookie を使って中継を開かせない（Cross-Site WebSocket Hijacking 対策）。

    WebSocket には CORS が効かないので、Origin を自分で確かめる。ブラウザは必ず付けるので、無いものも通さない。
    """
    origin = websocket.headers.get("origin", "")
    return bool(origin) and origin_allowed(origin, websocket.headers.get("host", ""))


@router.websocket("/api/rooms/{room_id}/signaling")
async def ws_signaling(websocket: WebSocket, room_id: str):
    if not _origin_allowed(websocket):
        await websocket.close(code=_CLOSE_FORBIDDEN_ORIGIN)
        return
    viewer = current_principal(websocket)
    if viewer is None:
        await websocket.close(code=_CLOSE_UNAUTHORIZED)
        return
    try:
        room = rooms.get_room(room_id, viewer)
    except NotFoundError:
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    await relay(websocket, room["signaling_url"])


async def relay(websocket: WebSocket, signaling_url: str) -> None:
    """確かめ終えた WebSocket を受け入れ、Ayame へ中継する（ゲストの一時的なルームからも使う）。"""
    await websocket.accept()
    if not signaling_url:
        # ルームでサーバを選んでおらず、既定のサーバも決まっていない
        await websocket.close(code=_CLOSE_NO_SERVER)
        return
    try:
        async with connect(signaling_url, open_timeout=5, ping_interval=None, max_size=2**20) as upstream:
            await _relay(websocket, upstream)
    except (OSError, asyncio.TimeoutError, ConnectionClosed) as exc:
        logger.warning("signaling upstream unreachable: %s (%s)", signaling_url, type(exc).__name__)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=_CLOSE_UPSTREAM_UNREACHABLE)


async def _relay(websocket: WebSocket, upstream) -> None:
    """両方向に流し、どちらかが閉じたらもう片方も閉じる（Ayame の切断を、そのまま画面に伝えるため）。"""

    async def browser_to_ayame() -> None:
        try:
            while True:
                await upstream.send(await websocket.receive_text())
        except WebSocketDisconnect:
            pass

    async def ayame_to_browser() -> None:
        try:
            async for message in upstream:
                await websocket.send_text(message if isinstance(message, str) else message.decode())
        except ConnectionClosed:
            pass

    tasks = [asyncio.create_task(browser_to_ayame()), asyncio.create_task(ayame_to_browser())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await upstream.close()
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.close()
