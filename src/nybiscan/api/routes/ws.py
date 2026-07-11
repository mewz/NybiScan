"""WebSocket history stream.

Auth is via the Authorization: Bearer header or the Sec-WebSocket-Protocol token
subprotocol (convention: subprotocols ["nybiscan", "<token>"]). A ?token= query
param is deliberately NOT accepted: query strings leak secrets into logs, process
listings, and history. Unauthorized connections are closed with 1008.

Connected clients receive entry_created and entry_updated events, in that order
per flow (the writer publishes creates before updates within a flush).
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

_SUBPROTOCOL = "nybiscan"


def _extract_token(ws: WebSocket) -> Optional[str]:
    auth = ws.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :]
    proto = ws.headers.get("sec-websocket-protocol")
    if proto:
        parts = [p.strip() for p in proto.split(",")]
        if len(parts) >= 2 and parts[0] == _SUBPROTOCOL:
            return parts[1]
    return None


@router.websocket("/ws/history")
async def ws_history(ws: WebSocket):
    state = ws.app.state.app_state
    token = _extract_token(ws)
    if not token or not secrets.compare_digest(token, state.token):
        # Reject the handshake before accepting.
        await ws.close(code=1008)
        return

    used_subprotocol = ws.headers.get("sec-websocket-protocol") is not None
    if used_subprotocol:
        await ws.accept(subprotocol=_SUBPROTOCOL)
    else:
        await ws.accept()

    queue = state.ws_hub.register()
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_hub.unregister(queue)
