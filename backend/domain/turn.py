"""Cloudflare の TURN（Realtime TURN）の認証情報を発行して、Ayame の accept に載せる ICE サーバを作る。

サーバの種類が cloudflare のとき、Ayame の認証 Webhook で入室を許すたびに呼ぶ。
返した iceServers は、Ayame が accept メッセージでブラウザと Kazami の両方に渡す。

- 認証情報は CREDENTIAL_TTL_SECONDS のあいだ使える。発行のたびに Cloudflare を呼ばないよう、
  CACHE_SECONDS だけ覚えて使い回す（渡した時点で、残りは必ず CREDENTIAL_TTL - CACHE 以上ある）
- Webhook は Ayame 側で 5 秒で打ち切られるので、Cloudflare の呼び出しは短く打ち切る。
  発行できなかったときは Cloudflare の STUN だけを渡す（同じネットワークや P2P で届く相手なら、それでつながる）
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from core.kv import get_store

logger = logging.getLogger(__name__)

API_URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"
CREDENTIAL_TTL_SECONDS = 24 * 60 * 60
CACHE_SECONDS = 60 * 60
REQUEST_TIMEOUT_SECONDS = 3
FALLBACK_ICE_SERVERS: list[dict[str, Any]] = [{"urls": ["stun:stun.cloudflare.com:3478"]}]

# ポート 53 の URL はブラウザが使えず、待たされるだけなので除く（Cloudflare の資料でも勧めている）
_PORT_53 = re.compile(r":53(\?|$)")


def _without_port_53(ice_servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for server in ice_servers:
        urls = server.get("urls")
        urls = [urls] if isinstance(urls, str) else list(urls or [])
        kept = [url for url in urls if not _PORT_53.search(url)]
        if kept:
            result.append({**server, "urls": kept})
    return result


def _generate(key_id: str, api_token: str) -> list[dict[str, Any]]:
    response = requests.post(
        API_URL.format(key_id=key_id),
        headers={"Authorization": f"Bearer {api_token}"},
        json={"ttl": CREDENTIAL_TTL_SECONDS},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    ice_servers = response.json().get("iceServers")
    if not isinstance(ice_servers, list):
        raise ValueError("iceServers missing in response")
    return _without_port_53(ice_servers)


def ice_servers(config: dict[str, str]) -> list[dict[str, Any]]:
    """config は servers.ice_server_config() の戻り値。サーバを編集したら（updated_at が変わったら）発行し直す。"""
    cache_key = f"turn-ice:{config['server_id']}:{config['updated_at']}"
    store = get_store()
    cached = store.get(cache_key)
    if cached is not None:
        return json.loads(cached)
    try:
        servers = _generate(config["key_id"], config["api_token"])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("cloudflare turn credentials unavailable: server=%s (%s)", config["server_id"], type(exc).__name__)
        return FALLBACK_ICE_SERVERS
    store.set(cache_key, json.dumps(servers), CACHE_SECONDS)
    return servers
