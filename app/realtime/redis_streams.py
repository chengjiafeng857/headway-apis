from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.config import settings
from app.models import OutboxEvent


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class RedisStreamsPublisher:
    def __init__(self, redis: Redis | None = None, stream_name: str | None = None) -> None:
        self.redis = redis or Redis.from_url(settings.redis_url, decode_responses=False)
        self.stream_name = stream_name or settings.redis_notifications_stream

    async def publish(self, event: OutboxEvent) -> str:
        message_id = await self.redis.xadd(
            self.stream_name,
            {
                "outbox_event_id": str(event.id),
                "event_type": event.event_type,
                "user_id": str(event.user_id),
                "payload": json.dumps(event.payload, separators=(",", ":")),
            },
        )
        return _decode(message_id)

    async def close(self) -> None:
        await self.redis.aclose()


class RedisStreamsConsumer:
    def __init__(self, redis: Redis | None = None, stream_name: str | None = None) -> None:
        self.redis = redis or Redis.from_url(settings.redis_url, decode_responses=False)
        self.stream_name = stream_name or settings.redis_notifications_stream

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.stream_name,
                settings.redis_consumer_group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_events(self, count: int = 10, block_ms: int = 1000) -> list[tuple[str, dict]]:
        raw_messages = await self.redis.xreadgroup(
            settings.redis_consumer_group,
            settings.redis_consumer_name,
            streams={self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        events: list[tuple[str, dict]] = []
        for _stream, messages in raw_messages:
            for raw_id, fields in messages:
                decoded_fields = {_decode(key): _decode(value) for key, value in fields.items()}
                payload = json.loads(decoded_fields["payload"])
                payload.setdefault("user_id", int(decoded_fields["user_id"]))
                events.append((_decode(raw_id), payload))
        return events

    async def ack(self, message_id: str) -> None:
        await self.redis.xack(self.stream_name, settings.redis_consumer_group, message_id)

    async def close(self) -> None:
        await self.redis.aclose()
