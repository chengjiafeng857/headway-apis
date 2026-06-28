from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.enums import SlotStatus
from app.models import AvailabilitySlot, InsurancePlan, ProviderProfile, Specialty
from app.schemas import (
    AvailabilitySlotRead,
    InsurancePlanRead,
    ProviderDetail,
    ProviderSummary,
)

router = APIRouter(tags=["providers"])


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


@router.get("/providers", response_model=list[ProviderSummary])
def list_providers(
    specialty: str | None = None,
    insurance_plan_id: int | None = None,
    city: str | None = None,
    state: str | None = None,
    care_type: str | None = Query(default=None, pattern="^(virtual|in_person)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
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


@router.get("/providers/{provider_id}", response_model=ProviderDetail)
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> ProviderDetail:
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


@router.get("/providers/{provider_id}/availability", response_model=list[AvailabilitySlotRead])
def get_provider_availability(
    provider_id: int,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    db: Session = Depends(get_db),
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


@router.get("/insurance-plans", response_model=list[InsurancePlanRead])
def list_insurance_plans(db: Session = Depends(get_db)) -> list[InsurancePlan]:
    return db.scalars(select(InsurancePlan).order_by(InsurancePlan.display_name)).all()
