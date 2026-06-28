from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, User


def list_my_notifications(
    db: Session,
    current_user: User,
    is_read: bool | None,
    limit: int,
    offset: int,
) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == current_user.id)
    if is_read is not None:
        query = query.where(Notification.is_read.is_(is_read))
    return db.scalars(
        query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    ).all()


def mark_notification_read(
    db: Session,
    current_user: User,
    notification_id: int,
) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.is_read = True
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification
