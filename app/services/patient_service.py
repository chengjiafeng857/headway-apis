from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ConsentForm,
    EmergencyContact,
    InsurancePlan,
    PatientAddress,
    PatientConsentAcknowledgement,
    PatientProfile,
    User,
)
from app.schemas import (
    EmergencyContactCreate,
    EmergencyContactUpdate,
    PatientAddressCreate,
    PatientAddressUpdate,
    PatientConsentRead,
    PatientInfoFormsRead,
    PatientProfileCreate,
    PatientProfileRead,
    PatientProfileUpdate,
    PatientAddressRead,
    EmergencyContactRead,
)
from app.services.authorization import ensure_patient


def _ensure_non_empty_payload(updates: dict) -> None:
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided",
        )


def _validate_insurance_plan(db: Session, insurance_plan_id: int | None) -> None:
    if insurance_plan_id is None:
        return
    plan_exists = db.scalar(select(InsurancePlan.id).where(InsurancePlan.id == insurance_plan_id))
    if plan_exists is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown insurance plan id",
        )


def _load_my_profile(db: Session, current_user: User) -> PatientProfile:
    ensure_patient(current_user)
    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return profile


def create_my_profile(
    db: Session,
    current_user: User,
    payload: PatientProfileCreate,
) -> PatientProfile:
    ensure_patient(current_user)
    updates = payload.model_dump(exclude_unset=True)
    _ensure_non_empty_payload(updates)
    _validate_insurance_plan(db, updates.get("insurance_plan_id"))

    existing = db.scalar(select(PatientProfile.id).where(PatientProfile.user_id == current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Patient profile already exists",
        )

    profile = PatientProfile(user_id=current_user.id, **updates)
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Patient profile already exists",
        )
    db.refresh(profile)
    return profile


def get_my_info_forms(db: Session, current_user: User) -> PatientInfoFormsRead:
    ensure_patient(current_user)
    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == current_user.id))
    addresses = list_my_addresses(db, current_user)
    emergency_contacts = list_my_emergency_contacts(db, current_user)
    consents = list_my_consents(db, current_user)
    return PatientInfoFormsRead(
        profile=PatientProfileRead.model_validate(profile) if profile else None,
        addresses=[PatientAddressRead.model_validate(address) for address in addresses],
        emergency_contacts=[
            EmergencyContactRead.model_validate(contact) for contact in emergency_contacts
        ],
        consents=consents,
    )


def update_my_profile(
    db: Session,
    current_user: User,
    payload: PatientProfileUpdate,
) -> PatientProfile:
    profile = _load_my_profile(db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    _ensure_non_empty_payload(updates)
    _validate_insurance_plan(db, updates.get("insurance_plan_id"))
    for field, value in updates.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


def _unset_primary_addresses(db: Session, patient_id: int) -> None:
    for address in db.scalars(
        select(PatientAddress).where(
            PatientAddress.patient_id == patient_id,
            PatientAddress.is_primary.is_(True),
        )
    ):
        address.is_primary = False


def _load_my_address(db: Session, current_user: User, address_id: int) -> PatientAddress:
    ensure_patient(current_user)
    address = db.scalar(
        select(PatientAddress).where(
            PatientAddress.id == address_id,
            PatientAddress.patient_id == current_user.id,
        )
    )
    if address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return address


def list_my_addresses(db: Session, current_user: User) -> list[PatientAddress]:
    ensure_patient(current_user)
    return db.scalars(
        select(PatientAddress)
        .where(PatientAddress.patient_id == current_user.id)
        .order_by(PatientAddress.is_primary.desc(), PatientAddress.created_at)
    ).all()


def create_my_address(
    db: Session,
    current_user: User,
    payload: PatientAddressCreate,
) -> PatientAddress:
    ensure_patient(current_user)
    address_count = db.scalar(
        select(func.count(PatientAddress.id)).where(PatientAddress.patient_id == current_user.id)
    )
    is_primary = payload.is_primary or address_count == 0
    if is_primary:
        _unset_primary_addresses(db, current_user.id)

    address = PatientAddress(
        patient_id=current_user.id,
        **payload.model_dump(exclude={"is_primary"}),
        is_primary=is_primary,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


def update_my_address(
    db: Session,
    current_user: User,
    address_id: int,
    payload: PatientAddressUpdate,
) -> PatientAddress:
    address = _load_my_address(db, current_user, address_id)
    updates = payload.model_dump(exclude_unset=True)
    _ensure_non_empty_payload(updates)
    if updates.get("is_primary") is True:
        _unset_primary_addresses(db, current_user.id)
    for field, value in updates.items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


def delete_my_address(db: Session, current_user: User, address_id: int) -> None:
    address = _load_my_address(db, current_user, address_id)
    db.delete(address)
    db.commit()


def _load_my_emergency_contact(
    db: Session,
    current_user: User,
    contact_id: int,
) -> EmergencyContact:
    ensure_patient(current_user)
    contact = db.scalar(
        select(EmergencyContact).where(
            EmergencyContact.id == contact_id,
            EmergencyContact.patient_id == current_user.id,
        )
    )
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emergency contact not found",
        )
    return contact


def list_my_emergency_contacts(db: Session, current_user: User) -> list[EmergencyContact]:
    ensure_patient(current_user)
    return db.scalars(
        select(EmergencyContact)
        .where(EmergencyContact.patient_id == current_user.id)
        .order_by(EmergencyContact.priority)
    ).all()


def create_my_emergency_contact(
    db: Session,
    current_user: User,
    payload: EmergencyContactCreate,
) -> EmergencyContact:
    ensure_patient(current_user)
    contact_count = db.scalar(
        select(func.count(EmergencyContact.id)).where(
            EmergencyContact.patient_id == current_user.id
        )
    )
    if contact_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At most two emergency contacts are allowed",
        )

    contact = EmergencyContact(patient_id=current_user.id, **payload.model_dump())
    db.add(contact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency contact priority already exists",
        )
    db.refresh(contact)
    return contact


def update_my_emergency_contact(
    db: Session,
    current_user: User,
    contact_id: int,
    payload: EmergencyContactUpdate,
) -> EmergencyContact:
    contact = _load_my_emergency_contact(db, current_user, contact_id)
    updates = payload.model_dump(exclude_unset=True)
    _ensure_non_empty_payload(updates)
    for field, value in updates.items():
        setattr(contact, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency contact priority already exists",
        )
    db.refresh(contact)
    return contact


def delete_my_emergency_contact(db: Session, current_user: User, contact_id: int) -> None:
    contact = _load_my_emergency_contact(db, current_user, contact_id)
    db.delete(contact)
    db.commit()


def _consent_read(
    consent_form: ConsentForm,
    acknowledgement: PatientConsentAcknowledgement | None,
) -> PatientConsentRead:
    accepted = acknowledgement is not None and acknowledgement.revoked_at is None
    return PatientConsentRead(
        form_key=consent_form.form_key,
        title=consent_form.title,
        version=consent_form.version,
        body_url=consent_form.body_url,
        is_required=consent_form.is_required,
        accepted=accepted,
        accepted_at=acknowledgement.accepted_at if acknowledgement else None,
        revoked_at=acknowledgement.revoked_at if acknowledgement else None,
    )


def list_my_consents(db: Session, current_user: User) -> list[PatientConsentRead]:
    ensure_patient(current_user)
    forms = db.scalars(
        select(ConsentForm)
        .where(ConsentForm.is_active.is_(True))
        .order_by(ConsentForm.is_required.desc(), ConsentForm.title)
    ).all()
    acknowledgements = db.scalars(
        select(PatientConsentAcknowledgement).where(
            PatientConsentAcknowledgement.patient_id == current_user.id
        )
    ).all()
    acknowledgements_by_form_id = {
        acknowledgement.consent_form_id: acknowledgement for acknowledgement in acknowledgements
    }
    return [
        _consent_read(consent_form, acknowledgements_by_form_id.get(consent_form.id))
        for consent_form in forms
    ]


def accept_my_consent(db: Session, current_user: User, form_key: str) -> PatientConsentRead:
    ensure_patient(current_user)
    consent_form = db.scalar(
        select(ConsentForm).where(
            ConsentForm.form_key == form_key,
            ConsentForm.is_active.is_(True),
        )
    )
    if consent_form is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consent form not found")

    acknowledgement = db.scalar(
        select(PatientConsentAcknowledgement).where(
            PatientConsentAcknowledgement.patient_id == current_user.id,
            PatientConsentAcknowledgement.consent_form_id == consent_form.id,
        )
    )
    accepted_at = datetime.now(UTC)
    if acknowledgement is None:
        acknowledgement = PatientConsentAcknowledgement(
            patient_id=current_user.id,
            consent_form_id=consent_form.id,
            form_version=consent_form.version,
            accepted_at=accepted_at,
        )
        db.add(acknowledgement)
    else:
        acknowledgement.form_version = consent_form.version
        acknowledgement.accepted_at = accepted_at
        acknowledgement.revoked_at = None

    db.commit()
    db.refresh(acknowledgement)
    return _consent_read(consent_form, acknowledgement)
