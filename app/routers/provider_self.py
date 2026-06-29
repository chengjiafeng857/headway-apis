from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import AvailabilitySlot, User
from app.schemas import (
    AvailabilitySlotCreate,
    AvailabilitySlotRead,
    ProviderDetail,
    ProviderCareTypesUpdate,
    ProviderInsurancePlansUpdate,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    ProviderSlotRead,
    ProviderSpecialtiesUpdate,
    ProviderStyleTagsUpdate,
)
from app.services import provider_service

# Authenticated, provider-owned management of the data that is exposed publicly
# (read-only) by the providers router. Every route is scoped to the caller's own
# profile via get_current_user, so there is no cross-provider write surface.
router = APIRouter(prefix="/providers/me", tags=["provider self-service"])


@router.post("", response_model=ProviderDetail, status_code=status.HTTP_201_CREATED)
def create_my_profile(
    payload: ProviderProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.create_my_profile(db, current_user, payload)


@router.get("", response_model=ProviderDetail)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.get_my_profile(db, current_user)


@router.patch("", response_model=ProviderDetail)
def update_my_profile(
    payload: ProviderProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.update_my_profile(db, current_user, payload)


@router.post(
    "/availability",
    response_model=AvailabilitySlotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_my_slot(
    payload: AvailabilitySlotCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvailabilitySlot:
    return provider_service.create_my_slot(db, current_user, payload)


@router.get("/availability", response_model=list[ProviderSlotRead])
def list_my_slots(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProviderSlotRead]:
    return provider_service.list_my_slots(db, current_user, limit=limit, offset=offset)


@router.delete("/availability/{slot_id}", response_model=AvailabilitySlotRead)
def close_my_slot(
    slot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvailabilitySlot:
    return provider_service.close_my_slot(db, current_user, slot_id)


@router.put("/specialties", response_model=ProviderDetail)
def set_my_specialties(
    payload: ProviderSpecialtiesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.set_my_specialties(db, current_user, payload.specialty_ids)


@router.put("/insurance-plans", response_model=ProviderDetail)
def set_my_insurance_plans(
    payload: ProviderInsurancePlansUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.set_my_insurance_plans(db, current_user, payload.insurance_plan_ids)


@router.put("/style-tags", response_model=ProviderDetail)
def set_my_style_tags(
    payload: ProviderStyleTagsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.set_my_style_tags(db, current_user, payload.style_tag_ids)


@router.put("/care-types", response_model=ProviderDetail)
def set_my_care_types(
    payload: ProviderCareTypesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderDetail:
    return provider_service.set_my_care_types(db, current_user, payload.care_type_ids)
