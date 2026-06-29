from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.enums import SlotStatus
from app.models import AvailabilitySlot, InsurancePlan, ProviderProfile, Specialty, User
from app.schemas import (
    AvailabilitySlotCreate,
    InsurancePlanRead,
    ProviderDetail,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    ProviderSummary,
)
from app.services.authorization import ensure_provider


def provider_summary(provider: ProviderProfile) -> ProviderSummary:
    return ProviderSummary(
        id=provider.id,
        display_name=provider.display_name,
        city=provider.city,
        state=provider.state,
        offers_virtual=provider.offers_virtual,
        offers_in_person=provider.offers_in_person,
        specialties=[specialty.name for specialty in provider.specialties],
        insurance_plans=[
            InsurancePlanRead.model_validate(plan) for plan in provider.insurance_plans
        ],
    )


def provider_detail(provider: ProviderProfile) -> ProviderDetail:
    summary = provider_summary(provider)
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
    limit: int,
    offset: int,
) -> list[ProviderSummary]:
    query = (
        select(ProviderProfile)
        .options(
            selectinload(ProviderProfile.specialties),
            selectinload(ProviderProfile.insurance_plans),
        )
        .distinct()
    )

    if specialty:
        query = query.join(ProviderProfile.specialties).where(Specialty.name.ilike(specialty))
    if insurance_plan_id:
        query = query.join(ProviderProfile.insurance_plans).where(
            InsurancePlan.id == insurance_plan_id
        )
    if city:
        query = query.where(ProviderProfile.city.ilike(city))
    if state:
        query = query.where(ProviderProfile.state.ilike(state))
    if care_type == "virtual":
        query = query.where(ProviderProfile.offers_virtual.is_(True))
    if care_type == "in_person":
        query = query.where(ProviderProfile.offers_in_person.is_(True))

    providers = db.scalars(
        query.order_by(ProviderProfile.display_name).offset(offset).limit(limit)
    ).all()
    return [provider_summary(provider) for provider in providers]


def get_provider(db: Session, provider_id: int) -> ProviderDetail:
    provider = db.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.id == provider_id)
        .options(
            selectinload(ProviderProfile.specialties),
            selectinload(ProviderProfile.insurance_plans),
        )
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return provider_detail(provider)


def list_provider_availability(
    db: Session,
    provider_id: int,
    start_after: datetime | None,
    start_before: datetime | None,
) -> list[AvailabilitySlot]:
    provider_exists = db.scalar(select(ProviderProfile.id).where(ProviderProfile.id == provider_id))
    if provider_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    query = select(AvailabilitySlot).where(
        AvailabilitySlot.provider_id == provider_id,
        AvailabilitySlot.status == SlotStatus.open.value,
    )
    if start_after:
        query = query.where(AvailabilitySlot.start_at >= start_after)
    if start_before:
        query = query.where(AvailabilitySlot.start_at <= start_before)

    return db.scalars(query.order_by(AvailabilitySlot.start_at)).all()


def list_insurance_plans(db: Session) -> list[InsurancePlan]:
    return db.scalars(select(InsurancePlan).order_by(InsurancePlan.display_name)).all()


# --- Provider self-service -------------------------------------------------
# These operate strictly on the authenticated provider's own profile, so
# ownership is implicit: every lookup is scoped to current_user.id.


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
        bio=payload.bio,
        city=payload.city,
        state=payload.state,
        timezone=payload.timezone,
        offers_virtual=payload.offers_virtual,
        offers_in_person=payload.offers_in_person,
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
) -> list[AvailabilitySlot]:
    profile = _load_my_profile(db, current_user)
    return db.scalars(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.provider_id == profile.id)
        .order_by(AvailabilitySlot.start_at)
        .offset(offset)
        .limit(limit)
    ).all()


def close_my_slot(db: Session, current_user: User, slot_id: int) -> None:
    # Soft-close (status -> cancelled) rather than delete, so historical
    # appointments and notifications that reference the slot stay intact.
    profile = _load_my_profile(db, current_user)
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
    if slot.status == SlotStatus.booked.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot close a booked slot; cancel the appointment first",
        )
    slot.status = SlotStatus.cancelled.value
    db.commit()


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
