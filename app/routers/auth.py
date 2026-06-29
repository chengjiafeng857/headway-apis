from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.enums import UserRole
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserRead
from app.services import auth_service, oauth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    return auth_service.register_user(db, payload)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return auth_service.login_user(db, payload)


@router.get("/oauth/{provider}/login", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
def oauth_login(
    provider: str,
    request: Request,
    role: UserRole = Query(UserRole.patient),
) -> RedirectResponse:
    authorization = oauth_service.build_authorization_request(provider, request, role)
    response = RedirectResponse(authorization.url)
    response.set_cookie(
        "oauth_state",
        authorization.state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/oauth/{provider}/callback", response_model=TokenResponse)
def oauth_callback(
    provider: str,
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
) -> TokenResponse:
    token_response = oauth_service.complete_authorization_code_login(
        db=db,
        provider=provider,
        request=request,
        code=code,
        state=state,
        state_cookie=request.cookies.get("oauth_state"),
        provider_error=error,
        provider_error_description=error_description,
    )
    response.delete_cookie("oauth_state")
    return token_response


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
