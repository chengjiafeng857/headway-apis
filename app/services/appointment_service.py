from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import AppointmentStatus, NotificationType, SlotStatus, UserRole
from app.models import (
    AppointmentRequest,
    AvailabilitySlot,
    Notification,
    SlotWatcher,
    User,
)
from app.services.authorization import (
    can_manage_appointment,
    ensure_patient,
    get_provider_profile_for_user,
)
from app.services.outbox_service import create_notification_outbox_event


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _create_reopened_slot_notifications(
    db: Session,
    slot: AvailabilitySlot,
    appointment: AppointmentRequest,
) -> None:
    watchers = db.scalars(
        select(SlotWatcher).where(
            SlotWatcher.provider_id == slot.provider_id,
            SlotWatcher.is_active.is_(True),
            SlotWatcher.start_after <= slot.start_at,
            SlotWatcher.start_before >= slot.start_at,
            SlotWatcher.patient_id != appointment.patient_id,
        )
    ).all()

    for watcher in watchers:
        existing_notification = db.scalar(
            select(Notification.id).where(
                Notification.user_id == watcher.patient_id,
                Notification.slot_id == slot.id,
                Notification.appointment_request_id == appointment.id,
                Notification.type == NotificationType.slot_reopened.value,
            )
        )
        if existing_notification:
            continue
        notification = Notification(
            user_id=watcher.patient_id,
            slot=slot,
            appointment_request=appointment,
            type=NotificationType.slot_reopened.value,
            message=(
                f"A slot reopened with provider {appointment.provider.display_name} "
                f"at {slot.start_at.isoformat()}."
            ),
        )
        db.add(notification)
        db.flush()
        create_notification_outbox_event(db, notification)


def _reopen_slot_and_notify(
    db: Session,
    appointment: AppointmentRequest,
    slot: AvailabilitySlot,
) -> None:
    slot.status = SlotStatus.open.value
    _create_reopened_slot_notifications(db, slot, appointment)


def create_appointment_request(
    db: Session,
    current_user: User,
    provider_id: int,
    slot_id: int,
    reason: str | None,
) -> AppointmentRequest:
    ensure_patient(current_user)

    slot = db.scalar(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == slot_id)
        .with_for_update()
    )
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")
    if slot.provider_id != provider_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slot does not belong to requested provider",
        )
    if _as_utc(slot.start_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot book past slot")

    updated = db.execute(
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.id == slot_id,
            AvailabilitySlot.status == SlotStatus.open.value,
        )
        .values(status=SlotStatus.booked.value)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slot is no longer open")

    appointment = AppointmentRequest(
        patient_id=current_user.id,
        provider_id=provider_id,
        slot_id=slot_id,
        status=AppointmentStatus.pending.value,
        reason=reason,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slot is already booked")
    db.refresh(appointment)
    return appointment


def list_my_appointments(
    db: Session,
    current_user: User,
    limit: int,
    offset: int,
) -> list[AppointmentRequest]:
    return db.scalars(
        select(AppointmentRequest)
        .where(AppointmentRequest.patient_id == current_user.id)
        .order_by(AppointmentRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()


def list_provider_appointments(
    db: Session,
    current_user: User,
    provider_id: int | None,
    limit: int,
    offset: int,
) -> list[AppointmentRequest]:
    if current_user.role == UserRole.provider.value:
        provider = get_provider_profile_for_user(db, current_user)
        query_provider_id = provider.id
    elif current_user.role == UserRole.admin.value:
        query_provider_id = provider_id
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider/admin only")

    query = select(AppointmentRequest).order_by(AppointmentRequest.created_at.desc())
    if query_provider_id is not None:
        query = query.where(AppointmentRequest.provider_id == query_provider_id)
    return db.scalars(query.offset(offset).limit(limit)).all()


def update_appointment_status(
    db: Session,
    current_user: User,
    appointment_id: int,
    new_status: AppointmentStatus,
    reason: str | None,
) -> AppointmentRequest:
    appointment = db.scalar(
        select(AppointmentRequest)
        .where(AppointmentRequest.id == appointment_id)
        .with_for_update()
    )
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    if not can_manage_appointment(db, current_user, appointment):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider/admin only")

    if new_status == AppointmentStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot move back to pending")
    if appointment.status in {
        AppointmentStatus.cancelled.value,
        AppointmentStatus.completed.value,
    } and appointment.status != new_status.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment is already finalized",
        )

    slot = db.scalar(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == appointment.slot_id)
        .with_for_update()
    )
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    appointment.status = new_status.value
    if new_status == AppointmentStatus.cancelled:
        appointment.cancelled_reason = reason
    if new_status in {AppointmentStatus.cancelled, AppointmentStatus.declined}:
        _reopen_slot_and_notify(db, appointment, slot)

    db.commit()
    db.refresh(appointment)
    return appointment


def cancel_appointment(
    db: Session,
    current_user: User,
    appointment_id: int,
    reason: str | None,
) -> AppointmentRequest:
    appointment = db.scalar(
        select(AppointmentRequest)
        .where(AppointmentRequest.id == appointment_id)
        .with_for_update()
    )
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if current_user.role == UserRole.patient.value:
        allowed = appointment.patient_id == current_user.id
    else:
        allowed = can_manage_appointment(db, current_user, appointment)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot cancel appointment")

    if appointment.status in {
        AppointmentStatus.cancelled.value,
        AppointmentStatus.completed.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment is already finalized",
        )

    slot = db.scalar(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == appointment.slot_id)
        .with_for_update()
    )
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    appointment.status = AppointmentStatus.cancelled.value
    appointment.cancelled_reason = reason
    _reopen_slot_and_notify(db, appointment, slot)
    db.commit()
    db.refresh(appointment)
    return appointment
