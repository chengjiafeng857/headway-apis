import asyncio

from app.realtime.manager import ConnectionManager, manager
from app.realtime.redis_streams import RedisStreamsConsumer


async def consume_redis_stream(
    stop_event: asyncio.Event,
    connection_manager: ConnectionManager = manager,
    consumer: RedisStreamsConsumer | None = None,
) -> None:
    stream_consumer = consumer or RedisStreamsConsumer()
    try:
        while not stop_event.is_set():
            try:
                await stream_consumer.ensure_group()
                events = await stream_consumer.read_events()
                for message_id, payload in events:
                    user_id = int(payload["user_id"])
                    await connection_manager.send_to_user(user_id, payload)
                    await stream_consumer.ack(message_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)
    finally:
        await stream_consumer.close()
