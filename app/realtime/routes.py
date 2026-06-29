from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.realtime.manager import manager

router = APIRouter(tags=["realtime"])


def _authenticate_websocket_token(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (ValueError, KeyError, TypeError):
        return None

    return db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))


@router.websocket("/ws/notifications")
async def notifications_websocket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    user = _authenticate_websocket_token(websocket.query_params.get("token"), db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(user.id, websocket)
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("event") == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(user.id, websocket)
