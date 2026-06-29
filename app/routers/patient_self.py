from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import EmergencyContact, PatientAddress, PatientProfile, User
from app.schemas import (
    EmergencyContactCreate,
    EmergencyContactRead,
    EmergencyContactUpdate,
    PatientAddressCreate,
    PatientAddressRead,
    PatientAddressUpdate,
    PatientConsentRead,
    PatientInfoFormsRead,
    PatientProfileCreate,
    PatientProfileRead,
    PatientProfileUpdate,
)
from app.services import patient_service

router = APIRouter(prefix="/patients/me", tags=["patient self-service"])


@router.post("/profile", response_model=PatientProfileRead, status_code=status.HTTP_201_CREATED)
def create_my_profile(
    payload: PatientProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientProfile:
    return patient_service.create_my_profile(db, current_user, payload)


@router.get("/profile", response_model=PatientInfoFormsRead)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientInfoFormsRead:
    return patient_service.get_my_info_forms(db, current_user)


@router.patch("/profile", response_model=PatientProfileRead)
def update_my_profile(
    payload: PatientProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientProfile:
    return patient_service.update_my_profile(db, current_user, payload)


@router.get("/addresses", response_model=list[PatientAddressRead])
def list_my_addresses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PatientAddress]:
    return patient_service.list_my_addresses(db, current_user)


@router.post("/addresses", response_model=PatientAddressRead, status_code=status.HTTP_201_CREATED)
def create_my_address(
    payload: PatientAddressCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientAddress:
    return patient_service.create_my_address(db, current_user, payload)


@router.patch("/addresses/{address_id}", response_model=PatientAddressRead)
def update_my_address(
    address_id: int,
    payload: PatientAddressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientAddress:
    return patient_service.update_my_address(db, current_user, address_id, payload)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_address(
    address_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    patient_service.delete_my_address(db, current_user, address_id)


@router.get("/emergency-contacts", response_model=list[EmergencyContactRead])
def list_my_emergency_contacts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmergencyContact]:
    return patient_service.list_my_emergency_contacts(db, current_user)


@router.post(
    "/emergency-contacts",
    response_model=EmergencyContactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_my_emergency_contact(
    payload: EmergencyContactCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmergencyContact:
    return patient_service.create_my_emergency_contact(db, current_user, payload)


@router.patch("/emergency-contacts/{contact_id}", response_model=EmergencyContactRead)
def update_my_emergency_contact(
    contact_id: int,
    payload: EmergencyContactUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmergencyContact:
    return patient_service.update_my_emergency_contact(db, current_user, contact_id, payload)


@router.delete("/emergency-contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_emergency_contact(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    patient_service.delete_my_emergency_contact(db, current_user, contact_id)


@router.get("/consents", response_model=list[PatientConsentRead])
def list_my_consents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PatientConsentRead]:
    return patient_service.list_my_consents(db, current_user)


@router.post("/consents/{form_key}/accept", response_model=PatientConsentRead)
def accept_my_consent(
    form_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientConsentRead:
    return patient_service.accept_my_consent(db, current_user, form_key)
