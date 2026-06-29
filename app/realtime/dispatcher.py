from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import SessionLocal
from app.realtime.in_process import InProcessPublisher
from app.services.outbox_service import OutboxPublisher, publish_pending_events


async def dispatch_outbox_events(
    stop_event: asyncio.Event,
    publisher: OutboxPublisher | None = None,
    poll_seconds: float | None = None,
) -> None:
    """Drain pending outbox events to connected sockets until stopped.

    Runs as an in-process background task (started from the app lifespan) so the
    payloads reach the same ``ConnectionManager`` that holds the live WebSocket
    connections. The DB read/commit inside ``publish_pending_events`` is
    synchronous and briefly blocks the event loop each poll; acceptable at
    single-instance scale, swap to a threadpool if it ever becomes hot.
    """
    # The default publisher targets this process's in-memory ConnectionManager,
    # so this dispatcher must run inside the API process that owns the sockets.
    outbox_publisher = publisher or InProcessPublisher()
    interval = poll_seconds if poll_seconds is not None else settings.outbox_poll_seconds

    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                await publish_pending_events(db, outbox_publisher)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stay alive across transient DB/delivery errors; durable truth is
            # still in the outbox table and will be retried next poll.
            pass
        await asyncio.sleep(interval)
