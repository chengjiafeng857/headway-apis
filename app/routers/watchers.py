from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.enums import UserRole
from app.models import ProviderProfile, SlotWatcher, User
from app.schemas import SlotWatcherCreate, SlotWatcherRead

router = APIRouter(prefix="/slot-watchers", tags=["slot watchers"])


def _ensure_patient(user: User) -> None:
    if user.role != UserRole.patient.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient role required")


@router.post("", response_model=SlotWatcherRead, status_code=status.HTTP_201_CREATED)
def create_slot_watcher(
    payload: SlotWatcherCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SlotWatcher:
    _ensure_patient(current_user)
    provider_exists = db.scalar(select(ProviderProfile.id).where(ProviderProfile.id == payload.provider_id))
    if provider_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    watcher = SlotWatcher(
        patient_id=current_user.id,
        provider_id=payload.provider_id,
        start_after=payload.start_after,
        start_before=payload.start_before,
        is_active=True,
    )
    db.add(watcher)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active watcher already exists for this window",
        )
    db.refresh(watcher)
    return watcher


@router.get("/me", response_model=list[SlotWatcherRead])
def list_my_watchers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SlotWatcher]:
    _ensure_patient(current_user)
    return db.scalars(
        select(SlotWatcher)
        .where(SlotWatcher.patient_id == current_user.id, SlotWatcher.is_active.is_(True))
        .order_by(SlotWatcher.created_at.desc())
    ).all()


@router.delete("/{watcher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slot_watcher(
    watcher_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    _ensure_patient(current_user)
    watcher = db.scalar(
        select(SlotWatcher).where(
            SlotWatcher.id == watcher_id,
            SlotWatcher.patient_id == current_user.id,
            SlotWatcher.is_active.is_(True),
        )
    )
    if watcher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watcher not found")
    watcher.is_active = False
    db.commit()
