from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ProviderFollow, ProviderProfile, User
from app.schemas import ProviderFollowCreate
from app.services.authorization import ensure_patient


def create_provider_follow(
    db: Session,
    current_user: User,
    payload: ProviderFollowCreate,
) -> ProviderFollow:
    ensure_patient(current_user)
    provider_exists = db.scalar(select(ProviderProfile.id).where(ProviderProfile.id == payload.provider_id))
    if provider_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    follow = ProviderFollow(
        patient_id=current_user.id,
        provider_id=payload.provider_id,
        is_active=True,
    )
    db.add(follow)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active provider follow already exists",
        )
    db.refresh(follow)
    return follow


def list_my_provider_follows(
    db: Session,
    current_user: User,
    limit: int,
    offset: int,
) -> list[ProviderFollow]:
    ensure_patient(current_user)
    return db.scalars(
        select(ProviderFollow)
        .where(ProviderFollow.patient_id == current_user.id, ProviderFollow.is_active.is_(True))
        .order_by(ProviderFollow.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()


def delete_provider_follow(db: Session, current_user: User, follow_id: int) -> None:
    ensure_patient(current_user)
    follow = db.scalar(
        select(ProviderFollow).where(
            ProviderFollow.id == follow_id,
            ProviderFollow.patient_id == current_user.id,
            ProviderFollow.is_active.is_(True),
        )
    )
    if follow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider follow not found")
    follow.is_active = False
    db.commit()
