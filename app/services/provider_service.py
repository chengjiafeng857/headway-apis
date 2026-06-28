from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.enums import SlotStatus
from app.models import AvailabilitySlot, InsurancePlan, ProviderProfile, Specialty
from app.schemas import InsurancePlanRead, ProviderDetail, ProviderSummary


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
