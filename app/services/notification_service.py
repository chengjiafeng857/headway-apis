from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.enums import NotificationType, UserRole
from app.models import (
    AppointmentRequest,
    AvailabilitySlot,
    Notification,
    ProviderFollow,
    SlotWatcher,
    User,
)
from app.services.outbox_service import create_notification_outbox_event


def _matching_provider_follower_ids(
    db: Session,
    slot: AvailabilitySlot,
    exclude_patient_id: int | None,
) -> set[int]:
    query = (
        select(ProviderFollow.patient_id)
        .join(User, User.id == ProviderFollow.patient_id)
        .where(
            ProviderFollow.provider_id == slot.provider_id,
            ProviderFollow.is_active.is_(True),
            User.role == UserRole.patient.value,
            User.is_active.is_(True),
        )
    )
    if exclude_patient_id is not None:
        query = query.where(ProviderFollow.patient_id != exclude_patient_id)
    return set(db.scalars(query).all())


def _matching_slot_watcher_ids(
    db: Session,
    slot: AvailabilitySlot,
    exclude_patient_id: int | None,
) -> set[int]:
    query = (
        select(SlotWatcher.patient_id)
        .join(User, User.id == SlotWatcher.patient_id)
        .where(
            SlotWatcher.provider_id == slot.provider_id,
            SlotWatcher.is_active.is_(True),
            SlotWatcher.start_after <= slot.start_at,
            SlotWatcher.start_before >= slot.start_at,
            User.role == UserRole.patient.value,
            User.is_active.is_(True),
        )
    )
    if exclude_patient_id is not None:
        query = query.where(SlotWatcher.patient_id != exclude_patient_id)
    return set(db.scalars(query).all())


def _slot_alert_recipient_ids(
    db: Session,
    slot: AvailabilitySlot,
    exclude_patient_id: int | None = None,
) -> set[int]:
    # Set union prevents a patient who both follows the provider and watches the
    # matching window from receiving two notifications for the same slot event.
    return _matching_provider_follower_ids(db, slot, exclude_patient_id) | _matching_slot_watcher_ids(
        db,
        slot,
        exclude_patient_id,
    )


def _notification_exists(
    db: Session,
    patient_id: int,
    slot_id: int,
    notification_type: NotificationType,
    appointment_request_id: int | None,
) -> bool:
    query = select(Notification.id).where(
        Notification.user_id == patient_id,
        Notification.slot_id == slot_id,
        Notification.type == notification_type.value,
    )
    if appointment_request_id is None:
        query = query.where(Notification.appointment_request_id.is_(None))
    else:
        query = query.where(Notification.appointment_request_id == appointment_request_id)
    # This is the cheap application-level dedupe; partial unique indexes on
    # notifications remain the concurrency-safe backstop at commit time.
    return db.scalar(query) is not None


def _create_slot_alert_notifications(
    db: Session,
    slot: AvailabilitySlot,
    notification_type: NotificationType,
    message: str,
    appointment: AppointmentRequest | None = None,
    exclude_patient_id: int | None = None,
) -> None:
    appointment_request_id = appointment.id if appointment is not None else None
    for patient_id in _slot_alert_recipient_ids(db, slot, exclude_patient_id):
        if _notification_exists(db, patient_id, slot.id, notification_type, appointment_request_id):
            continue
        notification = Notification(
            user_id=patient_id,
            slot=slot,
            appointment_request=appointment,
            type=notification_type.value,
            message=message,
        )
        db.add(notification)
        db.flush()
        # The payload snapshot is written before commit, so REST reconciliation
        # and realtime delivery refer to the same notification id.
        create_notification_outbox_event(db, notification)


def create_slot_opened_notifications(db: Session, slot: AvailabilitySlot) -> None:
    _create_slot_alert_notifications(
        db,
        slot=slot,
        notification_type=NotificationType.slot_opened,
        message=f"{slot.provider.display_name} opened a slot at {slot.start_at.isoformat()}.",
    )


def create_slot_reopened_notifications(
    db: Session,
    slot: AvailabilitySlot,
    appointment: AppointmentRequest,
) -> None:
    _create_slot_alert_notifications(
        db,
        slot=slot,
        notification_type=NotificationType.slot_reopened,
        message=(
            f"A slot reopened with provider {appointment.provider.display_name} "
            f"at {slot.start_at.isoformat()}."
        ),
        appointment=appointment,
        # The cancelling patient caused this reopen and should not be alerted
        # about their own cancellation.
        exclude_patient_id=appointment.patient_id,
    )


def list_my_notifications(
    db: Session,
    current_user: User,
    is_read: bool | None,
    limit: int,
    offset: int,
) -> list[Notification]:
    query = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .options(selectinload(Notification.slot).selectinload(AvailabilitySlot.provider))
    )
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
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .options(selectinload(Notification.slot).selectinload(AvailabilitySlot.provider))
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.is_read = True
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification
