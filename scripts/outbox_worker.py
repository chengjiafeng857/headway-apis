import asyncio

from app.core.database import SessionLocal
from app.realtime.redis_streams import RedisStreamsPublisher
from app.services.outbox_service import publish_pending_events


async def run_worker(poll_seconds: float = 1.0) -> None:
    publisher = RedisStreamsPublisher()
    try:
        while True:
            db = SessionLocal()
            try:
                await publish_pending_events(db, publisher)
            finally:
                db.close()
            await asyncio.sleep(poll_seconds)
    finally:
        await publisher.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
