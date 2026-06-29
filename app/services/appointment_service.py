from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.enums import AppointmentStatus, NotificationType, SlotStatus, UserRole
from app.models import (
    AppointmentRequest,
    AvailabilitySlot,
    User,
)
from app.services.authorization import (
    can_manage_appointment,
    ensure_patient,
    get_provider_profile_for_user,
)
from app.services.notification_service import (
    create_appointment_finalized_notification,
    create_slot_reopened_notifications,
)


ALLOWED_STATUS_TRANSITIONS = {
    AppointmentStatus.pending.value: {
        AppointmentStatus.confirmed,
        AppointmentStatus.declined,
        AppointmentStatus.cancelled,
    },
    AppointmentStatus.confirmed.value: {
        AppointmentStatus.completed,
        AppointmentStatus.declined,
        AppointmentStatus.cancelled,
    },
}

TERMINAL_APPOINTMENT_STATUSES = {
    AppointmentStatus.cancelled.value,
    AppointmentStatus.declined.value,
    AppointmentStatus.completed.value,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reopen_slot_and_notify(
    db: Session,
    appointment: AppointmentRequest,
    slot: AvailabilitySlot,
    patient_notification_type: NotificationType | None = None,
) -> None:
    # Slot reopening and notification/outbox creation happen in the caller's
    # transaction, so users cannot see a reopened slot without its alerts.
    slot.status = SlotStatus.open.value
    if patient_notification_type is not None:
        create_appointment_finalized_notification(db, appointment, slot, patient_notification_type)
    create_slot_reopened_notifications(db, slot, appointment)


def create_appointment_request(
    db: Session,
    current_user: User,
    provider_id: int,
    slot_id: int,
    reason: str | None,
) -> AppointmentRequest:
    ensure_patient(current_user)

    # Postgres serializes concurrent booking/closing/status changes here; SQLite
    # treats this as advisory, so real race tests must run against Postgres.
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

    # This conditional write is the booking race gate: only the first request
    # that still sees the slot as open can move it to booked.
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
        # The partial unique index is the final backstop against two live
        # appointments for one slot, including races or direct DB writes.
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
    query = (
        select(AppointmentRequest)
        .options(selectinload(AppointmentRequest.provider))
        .order_by(AppointmentRequest.created_at.desc())
    )
    if current_user.role == UserRole.provider.value:
        provider = get_provider_profile_for_user(db, current_user)
        query = query.where(AppointmentRequest.provider_id == provider.id)
    else:
        query = query.where(AppointmentRequest.patient_id == current_user.id)

    return db.scalars(
        query.offset(offset).limit(limit)
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

    query = (
        select(AppointmentRequest)
        .options(selectinload(AppointmentRequest.provider))
        .order_by(AppointmentRequest.created_at.desc())
    )
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
    # Serializes provider/admin status changes against patient cancellation on
    # Postgres; the terminal-state checks below reject whichever request loses.
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
    if appointment.status == new_status.value:
        return appointment
    if appointment.status in TERMINAL_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment is already finalized",
        )
    if new_status not in ALLOWED_STATUS_TRANSITIONS.get(appointment.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invalid appointment status transition",
        )

    # Lock the slot before reopening it, so decline/cancel does not race with
    # another slot-level operation in the same time window.
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
        patient_notification_type = (
            NotificationType.appointment_cancelled
            if new_status == AppointmentStatus.cancelled
            else NotificationType.appointment_declined
        )
        _reopen_slot_and_notify(db, appointment, slot, patient_notification_type)

    db.commit()
    db.refresh(appointment)
    return appointment


def cancel_appointment(
    db: Session,
    current_user: User,
    appointment_id: int,
    reason: str | None,
) -> AppointmentRequest:
    # Uses the same appointment lock as provider/admin status updates, so a
    # patient cancel and provider decline cannot both finalize the appointment.
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

    if appointment.status in TERMINAL_APPOINTMENT_STATUSES:
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
    # Reopening the slot and notifying interested patients are committed with
    # the cancellation; rollback removes both if any part fails.
    patient_notification_type = (
        None
        if current_user.role == UserRole.patient.value and current_user.id == appointment.patient_id
        else NotificationType.appointment_cancelled
    )
    _reopen_slot_and_notify(db, appointment, slot, patient_notification_type)
    db.commit()
    db.refresh(appointment)
    return appointment
