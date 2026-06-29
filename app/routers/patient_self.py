from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import EmergencyContact, PatientAddress, PatientProfile, User
from app.schemas import (
    EmergencyContactRead,
    EmergencyContactWrite,
    PatientAccountRead,
    PatientAddressCreate,
    PatientAddressRead,
    PatientConsentRead,
    PatientProfileRead,
    PatientProfileUpdate,
)
from app.services import patient_service

router = APIRouter(prefix="/patients/me", tags=["patient self-service"])


@router.get("/profile", response_model=PatientAccountRead)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientAccountRead:
    return patient_service.get_my_profile(db, current_user)


@router.patch("/profile", response_model=PatientProfileRead)
def update_my_profile(
    payload: PatientProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientProfile:
    return patient_service.update_my_profile(db, current_user, payload)


@router.put("/addresses", response_model=list[PatientAddressRead])
def replace_my_addresses(
    payload: list[PatientAddressCreate],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PatientAddress]:
    return patient_service.replace_my_addresses(db, current_user, payload)


@router.put("/emergency-contacts", response_model=list[EmergencyContactRead])
def replace_my_emergency_contacts(
    payload: list[EmergencyContactWrite],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmergencyContact]:
    return patient_service.replace_my_emergency_contacts(db, current_user, payload)


@router.post("/consents/{form_key}/accept", response_model=PatientConsentRead)
def accept_my_consent(
    form_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientConsentRead:
    return patient_service.accept_my_consent(db, current_user, form_key)
