from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.enums import AppointmentStatus, SlotStatus
from app.models import (
    AppointmentRequest,
    AvailabilitySlot,
    CareType,
    InsurancePlan,
    ProviderProfile,
    Specialty,
    StyleTag,
    User,
)
from app.schemas import (
    AvailabilitySlotCreate,
    AvailabilitySlotRead,
    InsurancePlanRead,
    ProviderAvailabilityRead,
    ProviderBrief,
    ProviderDetail,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    ProviderSlotRead,
    ProviderSummary,
)
from app.services.authorization import ensure_provider
from app.services.notification_service import create_slot_opened_notifications


def _next_available_at_by_provider(
    db: Session,
    provider_ids: list[int],
) -> dict[int, datetime]:
    if not provider_ids:
        return {}
    rows = db.execute(
        select(AvailabilitySlot.provider_id, func.min(AvailabilitySlot.start_at))
        .where(
            AvailabilitySlot.provider_id.in_(provider_ids),
            AvailabilitySlot.status == SlotStatus.open.value,
            AvailabilitySlot.start_at >= datetime.now(UTC),
        )
        .group_by(AvailabilitySlot.provider_id)
    ).all()
    return {provider_id: next_available_at for provider_id, next_available_at in rows}


def provider_summary(
    provider: ProviderProfile,
    next_available_at: datetime | None = None,
) -> ProviderSummary:
    return ProviderSummary(
        id=provider.id,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        credential=provider.credential,
        profile_photo_url=provider.profile_photo_url,
        quote=provider.quote,
        city=provider.city,
        state=provider.state,
        years_experience=provider.years_experience,
        gender=provider.gender,
        ethnicity=provider.ethnicity,
        languages=provider.languages,
        license_states=provider.license_states,
        offers_virtual=provider.offers_virtual,
        offers_in_person=provider.offers_in_person,
        offers_free_consultation=provider.offers_free_consultation,
        accepting_new_clients=provider.accepting_new_clients,
        next_available_at=next_available_at,
        specialties=[specialty.name for specialty in provider.specialties],
        style_tags=[style_tag.name for style_tag in provider.style_tags],
        care_types=[care_type.name for care_type in provider.care_types],
        insurance_plans=[
            InsurancePlanRead.model_validate(plan) for plan in provider.insurance_plans
        ],
    )


def provider_detail(
    provider: ProviderProfile,
    next_available_at: datetime | None = None,
) -> ProviderDetail:
    summary = provider_summary(provider, next_available_at=next_available_at)
    return ProviderDetail(
        **summary.model_dump(),
        bio=provider.bio,
        timezone=provider.timezone,
    )


def list_providers(
    db: Session,
    specialty: str | None,
    insurance_plan_id: int | None,
    city: str | None,
    state: str | None,
    care_type: str | None,
    session_mode: str | None,
    provider_type: str | None,
    style: str | None,
    gender: str | None,
    ethnicity: str | None,
    accepting_new_clients: bool | None,
    offers_free_consultation: bool | None,
    available_before: datetime | None,
    limit: int,
    offset: int,
) -> list[ProviderSummary]:
    resolved_session_mode = session_mode or care_type
    if session_mode and care_type and session_mode != care_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_mode and care_type filters must match when both are provided",
        )

    query = (
        select(ProviderProfile)
        .options(
            selectinload(ProviderProfile.specialties),
            selectinload(ProviderProfile.style_tags),
            selectinload(ProviderProfile.care_types),
            selectinload(ProviderProfile.insurance_plans),
        )
        .distinct()
    )

    if specialty:
        query = query.join(ProviderProfile.specialties).where(Specialty.name.ilike(specialty))
    if style:
        query = query.join(ProviderProfile.style_tags).where(StyleTag.name.ilike(style))
    if insurance_plan_id:
        query = query.join(ProviderProfile.insurance_plans).where(
            InsurancePlan.id == insurance_plan_id
        )
    if city:
        query = query.where(ProviderProfile.city.ilike(city))
    if state:
        query = query.where(ProviderProfile.state.ilike(state))
    if provider_type:
        query = query.where(ProviderProfile.provider_type.ilike(provider_type))
    if gender:
        query = query.where(ProviderProfile.gender.ilike(gender))
    if ethnicity:
        query = query.where(ProviderProfile.ethnicity.ilike(ethnicity))
    if accepting_new_clients is not None:
        query = query.where(ProviderProfile.accepting_new_clients.is_(accepting_new_clients))
    if offers_free_consultation is not None:
        query = query.where(
            ProviderProfile.offers_free_consultation.is_(offers_free_consultation)
        )
    if resolved_session_mode == "virtual":
        query = query.where(ProviderProfile.offers_virtual.is_(True))
    if resolved_session_mode == "in_person":
        query = query.where(ProviderProfile.offers_in_person.is_(True))
    if available_before:
        query = query.where(
            select(AvailabilitySlot.id)
            .where(
                AvailabilitySlot.provider_id == ProviderProfile.id,
                AvailabilitySlot.status == SlotStatus.open.value,
                AvailabilitySlot.start_at <= available_before,
            )
            .exists()
        )

    providers = db.scalars(
        query.order_by(ProviderProfile.display_name).offset(offset).limit(limit)
    ).all()
    next_available = _next_available_at_by_provider(db, [provider.id for provider in providers])
    return [
        provider_summary(provider, next_available_at=next_available.get(provider.id))
        for provider in providers
    ]


def get_provider(db: Session, provider_id: int) -> ProviderDetail:
    provider = db.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.id == provider_id)
        .options(
            selectinload(ProviderProfile.specialties),
            selectinload(ProviderProfile.style_tags),
            selectinload(ProviderProfile.care_types),
            selectinload(ProviderProfile.insurance_plans),
        )
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    next_available = _next_available_at_by_provider(db, [provider.id])
    return provider_detail(provider, next_available_at=next_available.get(provider.id))


def list_provider_availability(
    db: Session,
    provider_id: int,
    start_after: datetime | None,
    start_before: datetime | None,
) -> ProviderAvailabilityRead:
    provider = db.scalar(select(ProviderProfile).where(ProviderProfile.id == provider_id))
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    query = select(AvailabilitySlot).where(
        AvailabilitySlot.provider_id == provider_id,
        AvailabilitySlot.status == SlotStatus.open.value,
    )
    if start_after:
        query = query.where(AvailabilitySlot.start_at >= start_after)
    if start_before:
        query = query.where(AvailabilitySlot.start_at <= start_before)

    slots = db.scalars(query.order_by(AvailabilitySlot.start_at)).all()
    return ProviderAvailabilityRead(
        provider=ProviderBrief.model_validate(provider),
        slots=[AvailabilitySlotRead.model_validate(slot) for slot in slots],
    )


def list_insurance_plans(db: Session) -> list[InsurancePlan]:
    return db.scalars(select(InsurancePlan).order_by(InsurancePlan.display_name)).all()


# --- Provider self-service -------------------------------------------------
# These operate strictly on the authenticated provider's own profile, so
# ownership is implicit: every lookup is scoped to current_user.id.


def _ensure_offers_care_type(offers_virtual: bool, offers_in_person: bool) -> None:
    if not offers_virtual and not offers_in_person:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one care type must be offered",
        )


def _load_my_profile(db: Session, current_user: User) -> ProviderProfile:
    """Return the caller's own profile (with relations) or 404.

    Unlike authorization.get_provider_profile_for_user (which raises 403 for the
    appointment flow), a provider managing their own data should get a 404 when
    they simply have not created a profile yet.
    """
    ensure_provider(current_user)
    profile = db.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.user_id == current_user.id)
        .options(
            selectinload(ProviderProfile.specialties),
            selectinload(ProviderProfile.style_tags),
            selectinload(ProviderProfile.care_types),
            selectinload(ProviderProfile.insurance_plans),
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider profile not found")
    return profile


def create_my_profile(
    db: Session,
    current_user: User,
    payload: ProviderProfileCreate,
) -> ProviderDetail:
    ensure_provider(current_user)
    _ensure_offers_care_type(payload.offers_virtual, payload.offers_in_person)
    existing = db.scalar(
        select(ProviderProfile.id).where(ProviderProfile.user_id == current_user.id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider profile already exists",
        )

    profile = ProviderProfile(
        user_id=current_user.id,
        display_name=payload.display_name,
        provider_type=payload.provider_type,
        credential=payload.credential,
        profile_photo_url=payload.profile_photo_url,
        quote=payload.quote,
        bio=payload.bio,
        city=payload.city,
        state=payload.state,
        timezone=payload.timezone,
        years_experience=payload.years_experience,
        gender=payload.gender,
        ethnicity=payload.ethnicity,
        languages=payload.languages,
        license_states=payload.license_states,
        offers_virtual=payload.offers_virtual,
        offers_in_person=payload.offers_in_person,
        offers_free_consultation=payload.offers_free_consultation,
        accepting_new_clients=payload.accepting_new_clients,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider profile already exists",
        )
    db.refresh(profile)
    return provider_detail(profile)


def get_my_profile(db: Session, current_user: User) -> ProviderDetail:
    return provider_detail(_load_my_profile(db, current_user))


def update_my_profile(
    db: Session,
    current_user: User,
    payload: ProviderProfileUpdate,
) -> ProviderDetail:
    profile = _load_my_profile(db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided",
        )
    next_offers_virtual = updates.get("offers_virtual", profile.offers_virtual)
    next_offers_in_person = updates.get("offers_in_person", profile.offers_in_person)
    _ensure_offers_care_type(next_offers_virtual, next_offers_in_person)
    for field, value in updates.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return provider_detail(profile)


def create_my_slot(
    db: Session,
    current_user: User,
    payload: AvailabilitySlotCreate,
) -> AvailabilitySlot:
    profile = _load_my_profile(db, current_user)
    slot = AvailabilitySlot(
        provider_id=profile.id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        status=SlotStatus.open.value,
    )
    db.add(slot)
    try:
        db.flush()
        create_slot_opened_notifications(db, slot)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A slot with this time window already exists",
        )
    db.refresh(slot)
    return slot


def list_my_slots(
    db: Session,
    current_user: User,
    limit: int,
    offset: int,
) -> list[ProviderSlotRead]:
    profile = _load_my_profile(db, current_user)
    slots = db.scalars(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.provider_id == profile.id)
        .order_by(AvailabilitySlot.start_at)
        .offset(offset)
        .limit(limit)
    ).all()

    # Map each booked slot to the patient holding its active appointment. An
    # active appointment is one that has not been cancelled/declined (those
    # reopen the slot), so there is at most one per booked slot.
    booked_slot_ids = [slot.id for slot in slots if slot.status == SlotStatus.booked.value]
    booker_by_slot: dict[int, tuple[int, int, str, str]] = {}
    if booked_slot_ids:
        rows = db.execute(
            select(
                AppointmentRequest.slot_id,
                AppointmentRequest.id,
                AppointmentRequest.patient_id,
                User.full_name,
                User.email,
            )
            .join(User, User.id == AppointmentRequest.patient_id)
            .where(
                AppointmentRequest.slot_id.in_(booked_slot_ids),
                AppointmentRequest.status.notin_(
                    [AppointmentStatus.cancelled.value, AppointmentStatus.declined.value]
                ),
            )
        ).all()
        booker_by_slot = {
            slot_id: (appointment_id, patient_id, full_name, email)
            for slot_id, appointment_id, patient_id, full_name, email in rows
        }

    result: list[ProviderSlotRead] = []
    for slot in slots:
        booker = booker_by_slot.get(slot.id)
        result.append(
            ProviderSlotRead(
                id=slot.id,
                provider_id=slot.provider_id,
                start_at=slot.start_at,
                end_at=slot.end_at,
                status=slot.status,
                appointment_id=booker[0] if booker else None,
                patient_id=booker[1] if booker else None,
                patient_name=booker[2] if booker else None,
                patient_email=booker[3] if booker else None,
            )
        )
    return result


def close_my_slot(db: Session, current_user: User, slot_id: int) -> AvailabilitySlot:
    # Soft-close (status -> closed) rather than delete, so historical
    # appointments and notifications that reference the slot stay intact.
    profile = _load_my_profile(db, current_user)
    # Pairs with booking's slot lock on Postgres: close waits for an in-flight
    # booking, and booking waits for an in-flight close.
    slot = db.scalar(
        select(AvailabilitySlot)
        .where(
            AvailabilitySlot.id == slot_id,
            AvailabilitySlot.provider_id == profile.id,
        )
        .with_for_update()
    )
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")
    # If a booking committed while close was waiting, the provider must cancel
    # the appointment instead of silently hiding a booked slot.
    if slot.status == SlotStatus.booked.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot close a booked slot; cancel the appointment first",
        )
    if slot.status == SlotStatus.closed.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot is already closed",
        )
    slot.status = SlotStatus.closed.value
    db.commit()
    db.refresh(slot)
    return slot


def set_my_specialties(
    db: Session,
    current_user: User,
    specialty_ids: list[int],
) -> ProviderDetail:
    profile = _load_my_profile(db, current_user)
    unique_ids = list(dict.fromkeys(specialty_ids))
    specialties = (
        db.scalars(select(Specialty).where(Specialty.id.in_(unique_ids))).all()
        if unique_ids
        else []
    )
    found_ids = {specialty.id for specialty in specialties}
    missing = [specialty_id for specialty_id in unique_ids if specialty_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown specialty id(s): {missing}",
        )
    profile.specialties = list(specialties)
    db.commit()
    db.refresh(profile)
    return provider_detail(profile)


def set_my_insurance_plans(
    db: Session,
    current_user: User,
    insurance_plan_ids: list[int],
) -> ProviderDetail:
    profile = _load_my_profile(db, current_user)
    unique_ids = list(dict.fromkeys(insurance_plan_ids))
    plans = (
        db.scalars(select(InsurancePlan).where(InsurancePlan.id.in_(unique_ids))).all()
        if unique_ids
        else []
    )
    found_ids = {plan.id for plan in plans}
    missing = [plan_id for plan_id in unique_ids if plan_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown insurance plan id(s): {missing}",
        )
    profile.insurance_plans = list(plans)
    db.commit()
    db.refresh(profile)
    return provider_detail(profile)


def set_my_style_tags(
    db: Session,
    current_user: User,
    style_tag_ids: list[int],
) -> ProviderDetail:
    profile = _load_my_profile(db, current_user)
    unique_ids = list(dict.fromkeys(style_tag_ids))
    tags = (
        db.scalars(select(StyleTag).where(StyleTag.id.in_(unique_ids))).all()
        if unique_ids
        else []
    )
    found_ids = {tag.id for tag in tags}
    missing = [style_tag_id for style_tag_id in unique_ids if style_tag_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown style tag id(s): {missing}",
        )
    profile.style_tags = list(tags)
    db.commit()
    db.refresh(profile)
    return provider_detail(profile)


def set_my_care_types(
    db: Session,
    current_user: User,
    care_type_ids: list[int],
) -> ProviderDetail:
    profile = _load_my_profile(db, current_user)
    unique_ids = list(dict.fromkeys(care_type_ids))
    care_types = (
        db.scalars(select(CareType).where(CareType.id.in_(unique_ids))).all()
        if unique_ids
        else []
    )
    found_ids = {care_type.id for care_type in care_types}
    missing = [care_type_id for care_type_id in unique_ids if care_type_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown care type id(s): {missing}",
        )
    profile.care_types = list(care_types)
    db.commit()
    db.refresh(profile)
    return provider_detail(profile)
