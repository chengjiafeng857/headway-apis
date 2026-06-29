from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import UserRole
from app.models import AppointmentRequest, ProviderProfile, User


def ensure_patient(user: User) -> None:
    if user.role != UserRole.patient.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient role required")


def ensure_provider(user: User) -> None:
    if user.role != UserRole.provider.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider role required")


def get_provider_profile_for_user(db: Session, user: User) -> ProviderProfile:
    provider = db.scalar(select(ProviderProfile).where(ProviderProfile.user_id == user.id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Provider profile not found for user",
        )
    return provider


def can_manage_appointment(db: Session, user: User, appointment: AppointmentRequest) -> bool:
    if user.role == UserRole.admin.value:
        return True
    if user.role == UserRole.provider.value:
        provider = get_provider_profile_for_user(db, user)
        return appointment.provider_id == provider.id
    return False
