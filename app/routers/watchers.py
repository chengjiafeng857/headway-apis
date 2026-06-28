from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import SlotWatcher, User
from app.schemas import SlotWatcherCreate, SlotWatcherRead
from app.services import watcher_service

router = APIRouter(prefix="/slot-watchers", tags=["slot watchers"])


@router.post("", response_model=SlotWatcherRead, status_code=status.HTTP_201_CREATED)
def create_slot_watcher(
    payload: SlotWatcherCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SlotWatcher:
    return watcher_service.create_slot_watcher(db, current_user, payload)


@router.get("/me", response_model=list[SlotWatcherRead])
def list_my_watchers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SlotWatcher]:
    return watcher_service.list_my_watchers(db, current_user)


@router.delete("/{watcher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slot_watcher(
    watcher_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    watcher_service.delete_slot_watcher(db, current_user, watcher_id)
