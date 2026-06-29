from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

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
    EmergencyContactWrite,
    PatientAddressCreate,
    PatientAccountRead,
    PatientConsentRead,
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


def get_my_profile(db: Session, current_user: User) -> PatientAccountRead:
    ensure_patient(current_user)
    profile = db.scalar(
        select(PatientProfile)
        .where(PatientProfile.user_id == current_user.id)
        .options(selectinload(PatientProfile.insurance_plan))
    )
    addresses = list_my_addresses(db, current_user)
    emergency_contacts = list_my_emergency_contacts(db, current_user)
    consents = list_my_consents(db, current_user)
    return PatientAccountRead(
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
    ensure_patient(current_user)
    updates = payload.model_dump(exclude_unset=True)
    _ensure_non_empty_payload(updates)
    _validate_insurance_plan(db, updates.get("insurance_plan_id"))

    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == current_user.id))
    if profile is None:
        profile = PatientProfile(user_id=current_user.id, **updates)
        db.add(profile)
    else:
        for field, value in updates.items():
            setattr(profile, field, value)

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


def _normalize_address_primary_flags(
    payloads: list[PatientAddressCreate],
) -> list[tuple[PatientAddressCreate, bool]]:
    if not payloads:
        return []

    primary_indexes = [
        index for index, payload in enumerate(payloads) if payload.is_primary is True
    ]
    if len(primary_indexes) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At most one primary address is allowed",
        )

    primary_index = primary_indexes[0] if primary_indexes else 0
    return [(payload, index == primary_index) for index, payload in enumerate(payloads)]


def list_my_addresses(db: Session, current_user: User) -> list[PatientAddress]:
    ensure_patient(current_user)
    return db.scalars(
        select(PatientAddress)
        .where(PatientAddress.patient_id == current_user.id)
        .order_by(PatientAddress.is_primary.desc(), PatientAddress.created_at)
    ).all()


def replace_my_addresses(
    db: Session,
    current_user: User,
    payloads: list[PatientAddressCreate],
) -> list[PatientAddress]:
    ensure_patient(current_user)
    normalized_addresses = _normalize_address_primary_flags(payloads)

    db.execute(delete(PatientAddress).where(PatientAddress.patient_id == current_user.id))
    db.add_all(
        [
            PatientAddress(
                patient_id=current_user.id,
                **payload.model_dump(exclude={"is_primary"}),
                is_primary=is_primary,
            )
            for payload, is_primary in normalized_addresses
        ]
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Address replacement conflicts with existing data",
        )
    return list_my_addresses(db, current_user)


def _resolve_emergency_contact_priorities(
    payloads: list[EmergencyContactWrite],
) -> list[tuple[EmergencyContactWrite, int]]:
    if len(payloads) > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At most two emergency contacts are allowed",
        )

    explicit_priorities = [
        payload.priority for payload in payloads if payload.priority is not None
    ]
    if len(explicit_priorities) != len(set(explicit_priorities)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Emergency contact priorities must be unique",
        )

    available_priorities = [priority for priority in (1, 2) if priority not in explicit_priorities]
    resolved_contacts: list[tuple[EmergencyContactWrite, int]] = []
    for payload in payloads:
        priority = payload.priority
        if priority is None:
            priority = available_priorities.pop(0)
        resolved_contacts.append((payload, priority))
    return resolved_contacts


def replace_my_emergency_contacts(
    db: Session,
    current_user: User,
    payloads: list[EmergencyContactWrite],
) -> list[EmergencyContact]:
    ensure_patient(current_user)
    resolved_contacts = _resolve_emergency_contact_priorities(payloads)

    db.execute(delete(EmergencyContact).where(EmergencyContact.patient_id == current_user.id))
    db.add_all(
        [
            EmergencyContact(
                patient_id=current_user.id,
                **payload.model_dump(exclude={"priority"}),
                priority=priority,
            )
            for payload, priority in resolved_contacts
        ]
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency contact replacement conflicts with existing data",
        )
    return list_my_emergency_contacts(db, current_user)


def list_my_emergency_contacts(db: Session, current_user: User) -> list[EmergencyContact]:
    ensure_patient(current_user)
    return db.scalars(
        select(EmergencyContact)
        .where(EmergencyContact.patient_id == current_user.id)
        .order_by(EmergencyContact.priority)
    ).all()


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
