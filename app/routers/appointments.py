from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import AppointmentRequest, User
from app.schemas import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentRead,
    AppointmentStatusUpdate,
)
from app.services import appointment_service

router = APIRouter(prefix="/appointment-requests", tags=["appointments"])


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment_request(
    payload: AppointmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRequest:
    return appointment_service.create_appointment_request(
        db=db,
        current_user=current_user,
        provider_id=payload.provider_id,
        slot_id=payload.slot_id,
        reason=payload.reason,
    )


@router.get("/me", response_model=list[AppointmentRead])
def list_my_appointments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AppointmentRequest]:
    return appointment_service.list_my_appointments(db, current_user)


@router.get("/provider", response_model=list[AppointmentRead])
def list_provider_appointments(
    provider_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AppointmentRequest]:
    return appointment_service.list_provider_appointments(
        db=db,
        current_user=current_user,
        provider_id=provider_id,
    )


@router.patch("/{appointment_id}/status", response_model=AppointmentRead)
def update_appointment_status(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRequest:
    return appointment_service.update_appointment_status(
        db=db,
        current_user=current_user,
        appointment_id=appointment_id,
        new_status=payload.status,
        reason=payload.reason,
    )


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentCancel,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AppointmentRequest:
    return appointment_service.cancel_appointment(
        db=db,
        current_user=current_user,
        appointment_id=appointment_id,
        reason=payload.reason,
    )
