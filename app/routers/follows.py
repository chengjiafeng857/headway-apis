from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import ProviderFollow, User
from app.schemas import ProviderFollowCreate, ProviderFollowRead
from app.services import follow_service

router = APIRouter(prefix="/provider-follows", tags=["provider follows"])


@router.post("", response_model=ProviderFollowRead, status_code=status.HTTP_201_CREATED)
def create_provider_follow(
    payload: ProviderFollowCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderFollow:
    return follow_service.create_provider_follow(db, current_user, payload)


@router.get("/me", response_model=list[ProviderFollowRead])
def list_my_provider_follows(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProviderFollow]:
    return follow_service.list_my_provider_follows(db, current_user, limit=limit, offset=offset)


@router.delete("/{follow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_follow(
    follow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    follow_service.delete_provider_follow(db, current_user, follow_id)
