from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AvailabilitySlot, InsurancePlan
from app.schemas import (
    AvailabilitySlotRead,
    InsurancePlanRead,
    ProviderDetail,
    ProviderSummary,
)
from app.services import provider_service

router = APIRouter(tags=["providers"])


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
    return provider_service.list_providers(
        db=db,
        specialty=specialty,
        insurance_plan_id=insurance_plan_id,
        city=city,
        state=state,
        care_type=care_type,
        limit=limit,
        offset=offset,
    )


@router.get("/providers/{provider_id}", response_model=ProviderDetail)
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> ProviderDetail:
    return provider_service.get_provider(db, provider_id)


@router.get("/providers/{provider_id}/availability", response_model=list[AvailabilitySlotRead])
def get_provider_availability(
    provider_id: int,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    db: Session = Depends(get_db),
) -> list[AvailabilitySlot]:
    return provider_service.list_provider_availability(
        db=db,
        provider_id=provider_id,
        start_after=start_after,
        start_before=start_before,
    )


@router.get("/insurance-plans", response_model=list[InsurancePlanRead])
def list_insurance_plans(db: Session = Depends(get_db)) -> list[InsurancePlan]:
    return provider_service.list_insurance_plans(db)
