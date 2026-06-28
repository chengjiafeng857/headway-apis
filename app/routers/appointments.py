from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.enums import AppointmentStatus, NotificationType, SlotStatus, UserRole
from app.models import (
    AppointmentRequest,
    AvailabilitySlot,
    Notification,
    ProviderProfile,
    SlotWatcher,
    User,
)
from app.schemas import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentRead,
    AppointmentStatusUpdate,
)

router = APIRouter(prefix="/appointment-requests", tags=["appointments"])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _ensure_patient(user: User) -> None:
    if user.role != UserRole.patient.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient role required")


def _provider_profile_for_user(db: Session, user: User) -> ProviderProfile:
    provider = db.scalar(select(ProviderProfile).where(ProviderProfile.user_id == user.id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Provider profile not found for user",
        )
    return provider


def _can_manage_appointment(db: Session, user: User, appointment: AppointmentRequest) -> bool:
    if user.role == UserRole.admin.value:
        return True
    if user.role == UserRole.provider.value:
        provider = _provider_profile_for_user(db, user)
        return appointment.provider_id == provider.id
    return False


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
        db.add(
            Notification(
                user_id=watcher.patient_id,
                slot_id=slot.id,
                appointment_request_id=appointment.id,
                type=NotificationType.slot_reopened.value,
                message=(
                    f"A slot reopened with provider {appointment.provider.display_name} "
                    f"at {slot.start_at.isoformat()}."
                ),
            )
        )


def _reopen_slot_and_notify(
    db: Session,
    appointment: AppointmentRequest,
    slot: AvailabilitySlot,
) -> None:
    slot.status = SlotStatus.open.value
    _create_reopened_slot_notifications(db, slot, appointment)


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment_request(
    payload: AppointmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRequest:
    _ensure_patient(current_user)

    slot = db.scalar(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == payload.slot_id)
        .with_for_update()
    )
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")
    if slot.provider_id != payload.provider_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slot does not belong to requested provider",
        )
    if _as_utc(slot.start_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot book past slot")

    updated = db.execute(
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.id == payload.slot_id,
            AvailabilitySlot.status == SlotStatus.open.value,
        )
        .values(status=SlotStatus.booked.value)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slot is no longer open")

    appointment = AppointmentRequest(
        patient_id=current_user.id,
        provider_id=payload.provider_id,
        slot_id=payload.slot_id,
        status=AppointmentStatus.pending.value,
        reason=payload.reason,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slot is already booked")
    db.refresh(appointment)
    return appointment


@router.get("/me", response_model=list[AppointmentRead])
def list_my_appointments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AppointmentRequest]:
    return db.scalars(
        select(AppointmentRequest)
        .where(AppointmentRequest.patient_id == current_user.id)
        .order_by(AppointmentRequest.created_at.desc())
    ).all()


@router.get("/provider", response_model=list[AppointmentRead])
def list_provider_appointments(
    provider_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AppointmentRequest]:
    if current_user.role == UserRole.provider.value:
        provider = _provider_profile_for_user(db, current_user)
        query_provider_id = provider.id
    elif current_user.role == UserRole.admin.value:
        query_provider_id = provider_id
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider/admin only")

    query = select(AppointmentRequest).order_by(AppointmentRequest.created_at.desc())
    if query_provider_id is not None:
        query = query.where(AppointmentRequest.provider_id == query_provider_id)
    return db.scalars(query).all()


@router.patch("/{appointment_id}/status", response_model=AppointmentRead)
def update_appointment_status(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRequest:
    appointment = db.scalar(
        select(AppointmentRequest)
        .where(AppointmentRequest.id == appointment_id)
        .with_for_update()
    )
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    if not _can_manage_appointment(db, current_user, appointment):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider/admin only")

    if payload.status == AppointmentStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot move back to pending")
    if appointment.status in {
        AppointmentStatus.cancelled.value,
        AppointmentStatus.completed.value,
    } and appointment.status != payload.status.value:
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

    appointment.status = payload.status.value
    if payload.status == AppointmentStatus.cancelled:
        appointment.cancelled_reason = payload.reason
    if payload.status in {AppointmentStatus.cancelled, AppointmentStatus.declined}:
        _reopen_slot_and_notify(db, appointment, slot)

    db.commit()
    db.refresh(appointment)
    return appointment


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentCancel,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
        allowed = _can_manage_appointment(db, current_user, appointment)
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
    appointment.cancelled_reason = payload.reason
    _reopen_slot_and_notify(db, appointment, slot)
    db.commit()
    db.refresh(appointment)
    return appointment
