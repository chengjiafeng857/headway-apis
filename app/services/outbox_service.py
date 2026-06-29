from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enums import OutboxStatus
from app.models import Notification, OutboxEvent


class OutboxPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> str:
        """Publish an outbox event and return the broker message id."""


@dataclass(frozen=True)
class OutboxPublishResult:
    published: int
    failed: int


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def notification_realtime_payload(notification: Notification) -> dict:
    return {
        "event": notification.type,
        "notification_id": notification.id,
        "user_id": notification.user_id,
        "slot_id": notification.slot_id,
        "provider_id": notification.provider_id,
        "provider_name": notification.provider_name,
        "start_at": _iso_utc(notification.start_at),
        "end_at": _iso_utc(notification.end_at),
        "message": notification.message,
    }


def create_notification_outbox_event(db: Session, notification: Notification) -> OutboxEvent:
    outbox_event = OutboxEvent(
        event_type=notification.type,
        aggregate_type="notification",
        aggregate_id=notification.id,
        user_id=notification.user_id,
        payload=notification_realtime_payload(notification),
        status=OutboxStatus.pending.value,
    )
    db.add(outbox_event)
    return outbox_event


async def publish_pending_events(
    db: Session,
    publisher: OutboxPublisher,
    batch_size: int | None = None,
    max_attempts: int = 3,
) -> OutboxPublishResult:
    limit = batch_size or settings.outbox_batch_size
    events = db.scalars(
        select(OutboxEvent)
        .where(
            or_(
                OutboxEvent.status == OutboxStatus.pending.value,
                and_(
                    OutboxEvent.status == OutboxStatus.failed.value,
                    OutboxEvent.attempt_count < max_attempts,
                ),
            )
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    published = 0
    failed = 0
    for event in events:
        event.attempt_count += 1
        try:
            event.stream_message_id = await publisher.publish(event)
            event.status = OutboxStatus.published.value
            event.published_at = datetime.now(UTC)
            event.last_error = None
            published += 1
        except Exception as exc:  # pragma: no cover - exact Redis errors vary by deployment.
            event.last_error = str(exc)
            event.status = (
                OutboxStatus.failed.value
                if event.attempt_count >= max_attempts
                else OutboxStatus.pending.value
            )
            failed += 1
    db.commit()
    return OutboxPublishResult(published=published, failed=failed)
