from __future__ import annotations

from app.models import OutboxEvent
from app.realtime.manager import ConnectionManager, manager


class InProcessPublisher:
    """Outbox publisher that delivers straight to in-process WebSocket sockets.

    Implements the ``OutboxPublisher`` protocol so it is a drop-in replacement
    for a network broker. Because delivery targets the in-memory
    ``ConnectionManager``, the dispatcher that drives it must run inside the same
    process as the WebSocket connections (see ``app.realtime.dispatcher``).

    A user with no live socket is not an error: ``send_to_user`` returns 0, the
    outbox event is still marked published, and the durable ``notifications`` row
    remains the source of truth for the client to reconcile over REST.
    """

    def __init__(self, connection_manager: ConnectionManager = manager) -> None:
        self._manager = connection_manager

    async def publish(self, event: OutboxEvent) -> str:
        delivered = await self._manager.send_to_user(event.user_id, event.payload)
        return f"inprocess:{delivered}"
