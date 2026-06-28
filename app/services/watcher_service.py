from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ProviderProfile, SlotWatcher, User
from app.schemas import SlotWatcherCreate
from app.services.authorization import ensure_patient


def create_slot_watcher(
    db: Session,
    current_user: User,
    payload: SlotWatcherCreate,
) -> SlotWatcher:
    ensure_patient(current_user)
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


def list_my_watchers(
    db: Session,
    current_user: User,
    limit: int,
    offset: int,
) -> list[SlotWatcher]:
    ensure_patient(current_user)
    return db.scalars(
        select(SlotWatcher)
        .where(SlotWatcher.patient_id == current_user.id, SlotWatcher.is_active.is_(True))
        .order_by(SlotWatcher.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()


def delete_slot_watcher(db: Session, current_user: User, watcher_id: int) -> None:
    ensure_patient(current_user)
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
