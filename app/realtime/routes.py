import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.realtime.manager import manager

router = APIRouter(tags=["realtime"])


def _extract_ws_token(websocket: WebSocket) -> str | None:
    """Prefer the Authorization header (kept out of access logs) over the query
    string. Browsers can't set WebSocket headers, so the ``?token=`` query param
    remains the fallback for browser clients."""
    authorization = websocket.headers.get("authorization")
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            return credentials.strip()
    return websocket.query_params.get("token")


def _authenticate_websocket_token(
    token: str | None, db: Session
) -> tuple[User, datetime] | tuple[None, None]:
    if not token:
        return None, None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (ValueError, KeyError, TypeError):
        return None, None

    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        return None, None
    return user, expires_at


@router.websocket(
    "/ws/notifications",
    name="notifications_websocket",
)
async def notifications_websocket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    """Realtime notification stream. Connect with `?token=<access-token>`.

    Delivery is **best-effort**. Events fired while the user has no live socket
    (offline, page reload, flaky network) are dropped and never replayed over the
    socket — the durable record lives in the database. Clients MUST reconcile:

    1. On every (re)connect, call `GET /notifications/me?is_read=false` and render
       that backlog.
    2. Dedupe live socket events against the backlog by `notification_id`; socket
       events and REST rows carry the same id.

    Send `{"event": "ping"}` to receive `{"event": "pong"}`. The socket is closed
    with code 1008 once the access token expires; clients must reconnect with a
    fresh token.
    """
    user, expires_at = _authenticate_websocket_token(_extract_ws_token(websocket), db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(user.id, websocket)
    try:
        while True:
            timeout = (expires_at - datetime.now(UTC)).total_seconds()
            if timeout <= 0:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
            except asyncio.TimeoutError:
                # Token lifetime elapsed mid-connection; force a re-auth.
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break
            except ValueError:
                # Malformed (non-JSON) client frame: ignore it, keep the socket.
                continue
            if isinstance(message, dict) and message.get("event") == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        # Always run, so a malformed frame or any error can never leak a stale
        # registration in the ConnectionManager.
        await manager.disconnect(user.id, websocket)
