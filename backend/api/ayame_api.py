"""Ayame との連携。入室チケットの発行（ブラウザ用）と、Ayame から呼ばれる認証 Webhook。"""
from __future__ import annotations

import hmac
import ipaddress
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from config.settings import get_settings
from core.api_common import _request_json
from core.auth import Viewer
from domain import room_access

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/rooms/{room_id}/ticket")
def api_room_ticket(room_id: str, viewer: Viewer):
    """接続の直前に呼ぶ。Ayame に register するときの signalingKey に使う。"""
    return room_access.issue_room_ticket(room_id, viewer)


# リバースプロキシが付けるヘッダー。Ayame は付けないので、付いていれば外から来たもの
_FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")


def _from_ayame(request: Request) -> bool:
    """Ayame（許可した接続元）から直接届いたか。

    kazayomi を公開しても、この Webhook は外から呼べないようにする。
    接続元の IP だけでは足りない: 同じホストのリバースプロキシ（nginx など）を通ると、外からの
    リクエストも 127.0.0.1 から来たように見える。そのため、転送のヘッダーが付いていたら外からとみなす。
    """
    if any(name in request.headers for name in _FORWARDING_HEADERS):
        return False
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for allowed in get_settings().ayame_webhook_allowed_ips:
        try:
            if address in ipaddress.ip_network(allowed, strict=False):
                return True
        except ValueError:
            logger.warning("invalid entry in AYAME_WEBHOOK_ALLOWED_IPS: %s", allowed)
    return False


@router.post("/api/ayame/authn")
async def api_ayame_authn(request: Request, key: str = ""):
    """Ayame の authn_webhook_url に指定する。ログインは要らない（Ayame が呼ぶ）。

    呼べるのは AYAME_WEBHOOK_ALLOWED_IPS の接続元（既定は 127.0.0.1）から、プロキシを通さずに届いたものだけ。
    AYAME_WEBHOOK_SECRET を設定したときは、URL の ?key= の一致も求める。
    Ayame には 200 で可否（allowed）を返す。それ以外の呼び出しには 403 を返す。
    """
    if not _from_ayame(request):
        logger.warning("ayame authn webhook called from a disallowed source: %s",
                       request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="この URL は Ayame からだけ呼べます。")
    secret = get_settings().ayame_webhook_secret
    if secret and not hmac.compare_digest(key.encode(), secret.encode()):
        logger.warning("ayame authn webhook called with a wrong key")
        return {"allowed": False, "reason": "webhook key mismatch"}
    payload = await _request_json(request)
    # cloudflare のサーバでは TURN の認証情報を発行しに外へ出るので、イベントループを止めないよう別スレッドで
    result = await run_in_threadpool(room_access.authenticate, payload)
    if not result["allowed"]:
        logger.info("ayame authn denied: room=%s reason=%s", payload.get("roomId"), result.get("reason"))
    return result
