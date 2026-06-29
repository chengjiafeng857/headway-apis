from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, Request, status
import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import (
    OAuthConfigurationError,
    OAuthProviderConfig,
    get_oauth_provider_config,
    settings,
)
from app.core.security import create_access_token, create_unusable_password_hash
from app.enums import UserRole
from app.models import OAuthIdentity, User
from app.schemas import TokenResponse


_OAUTH_STATE_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class OAuthProfile:
    subject: str
    email: str
    full_name: str


@dataclass(frozen=True)
class OAuthAuthorizationRequest:
    url: str
    state: str


def build_authorization_request(
    provider: str, request: Request, role: UserRole
) -> OAuthAuthorizationRequest:
    if role == UserRole.admin:
        raise HTTPException(
            status_code=422,
            detail="admin users cannot self-register",
        )

    config = _load_provider_config(provider)
    redirect_uri = _callback_url(request, config.name)
    state = _encode_oauth_state({"provider": config.name, "role": role.value})
    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
    }
    separator = "&" if "?" in config.authorization_url else "?"
    return OAuthAuthorizationRequest(
        url=f"{config.authorization_url}{separator}{urlencode(params)}",
        state=state,
    )


def build_authorization_url(provider: str, request: Request, role: UserRole) -> str:
    return build_authorization_request(provider, request, role).url


def complete_authorization_code_login(
    db: Session,
    provider: str,
    request: Request,
    code: str | None,
    state: str | None,
    state_cookie: str | None,
    provider_error: str | None = None,
    provider_error_description: str | None = None,
) -> TokenResponse:
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth callback requires state",
        )
    if state_cookie != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    config = _load_provider_config(provider)
    state_payload = _decode_oauth_state(state)
    if state_payload.get("provider") != config.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    requested_role = _requested_role_from_state(state_payload)
    if provider_error:
        detail = f"OAuth provider returned error: {provider_error}"
        if provider_error_description:
            detail = f"{detail} - {provider_error_description}"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth callback requires code",
        )

    redirect_uri = _callback_url(request, config.name)
    token_payload = _exchange_authorization_code(config, code, redirect_uri)
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider did not return an access token",
        )

    userinfo = _fetch_userinfo(config, access_token)
    profile = _profile_from_userinfo(config, userinfo)
    user = _get_or_create_user_for_oauth(db, config, profile, requested_role)
    token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(access_token=token)


def _load_provider_config(provider: str) -> OAuthProviderConfig:
    try:
        return get_oauth_provider_config(provider)
    except OAuthConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _callback_url(request: Request, provider: str) -> str:
    return str(request.url_for("oauth_callback", provider=provider))


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _encode_oauth_state(claims: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + _OAUTH_STATE_TTL).timestamp()),
        "nonce": secrets.token_urlsafe(16),
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def _decode_oauth_state(state: str) -> dict[str, Any]:
    try:
        encoded_payload, encoded_signature = state.split(".", 1)
        expected_signature = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual_signature = _base64url_decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("bad signature")
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    return payload


def _requested_role_from_state(state_payload: dict[str, Any]) -> UserRole:
    try:
        role = UserRole(state_payload["role"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    if role == UserRole.admin:
        raise HTTPException(
            status_code=422,
            detail="admin users cannot self-register",
        )
    return role


def _exchange_authorization_code(
    config: OAuthProviderConfig, code: str, redirect_uri: str
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                config.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                },
                headers={"Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth token exchange failed",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth token exchange returned an invalid response",
        )
    return payload


def _fetch_userinfo(config: OAuthProviderConfig, access_token: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                config.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth userinfo request failed",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth userinfo returned an invalid response",
        )
    return payload


def _profile_from_userinfo(config: OAuthProviderConfig, userinfo: dict[str, Any]) -> OAuthProfile:
    subject = _claim_as_text(userinfo.get("sub"))
    email = _claim_as_text(userinfo.get("email")).lower()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider did not return a subject",
        )
    if not email:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider did not return an email",
        )
    if config.require_verified_email and not _claim_as_bool(userinfo.get("email_verified")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth provider did not verify the email address",
        )
    return OAuthProfile(subject=subject, email=email, full_name=_profile_name(userinfo, email))


def _claim_as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _claim_as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _profile_name(userinfo: dict[str, Any], email: str) -> str:
    name = _claim_as_text(userinfo.get("name"))
    if not name:
        given_name = _claim_as_text(userinfo.get("given_name"))
        family_name = _claim_as_text(userinfo.get("family_name"))
        name = " ".join(part for part in (given_name, family_name) if part)
    if not name:
        name = email.split("@", 1)[0]
    return name[:120]


def _get_or_create_user_for_oauth(
    db: Session,
    config: OAuthProviderConfig,
    profile: OAuthProfile,
    requested_role: UserRole,
) -> User:
    identity = db.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == config.name,
            OAuthIdentity.subject == profile.subject,
        )
    )
    if identity is not None:
        user = identity.user
        _ensure_oauth_user_active(user)
        if identity.email != profile.email:
            identity.email = profile.email
            db.commit()
            db.refresh(user)
        return user

    user = db.scalar(select(User).where(User.email == profile.email))
    if user is None:
        user = User(
            email=profile.email,
            hashed_password=create_unusable_password_hash(),
            full_name=profile.full_name,
            role=requested_role.value,
        )
        db.add(user)
        identity = OAuthIdentity(
            user=user,
            provider=config.name,
            subject=profile.subject,
            email=profile.email,
        )
    else:
        _ensure_oauth_user_active(user)
        identity = OAuthIdentity(
            user_id=user.id,
            provider=config.name,
            subject=profile.subject,
            email=profile.email,
        )
    db.add(identity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        identity = db.scalar(
            select(OAuthIdentity).where(
                OAuthIdentity.provider == config.name,
                OAuthIdentity.subject == profile.subject,
            )
        )
        if identity is not None:
            user = identity.user
            _ensure_oauth_user_active(user)
            return user
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OAuth account could not be linked",
        )
    db.refresh(user)
    return user


def _ensure_oauth_user_active(user: User) -> None:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
