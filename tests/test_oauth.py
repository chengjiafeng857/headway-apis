from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from app.models import OAuthIdentity, User
from app.services import oauth_service


@pytest.fixture()
def configured_oauth(monkeypatch):
    monkeypatch.setenv("OAUTH_TEST_CLIENT_ID", "client-id")
    monkeypatch.setenv("OAUTH_TEST_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("OAUTH_TEST_AUTHORIZATION_URL", "https://provider.example/authorize")
    monkeypatch.setenv("OAUTH_TEST_TOKEN_URL", "https://provider.example/token")
    monkeypatch.setenv("OAUTH_TEST_USERINFO_URL", "https://provider.example/userinfo")


def _oauth_login_state(client, role: str | None = None) -> tuple[str, dict[str, list[str]], str]:
    params = {"role": role} if role else {}
    response = client.get("/auth/oauth/test/login", params=params, follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)
    return query["state"][0], query, location


def _stub_oauth_provider(monkeypatch, userinfo: dict):
    seen = {}

    def exchange(config, code, redirect_uri):
        seen["code"] = code
        seen["redirect_uri"] = redirect_uri
        seen["token_url"] = config.token_url
        return {"access_token": "provider-access-token"}

    def fetch(config, access_token):
        seen["access_token"] = access_token
        seen["userinfo_url"] = config.userinfo_url
        return userinfo

    monkeypatch.setattr(oauth_service, "_exchange_authorization_code", exchange)
    monkeypatch.setattr(oauth_service, "_fetch_userinfo", fetch)
    return seen


def test_oauth_login_redirect_builds_authorization_request(client, configured_oauth):
    _state, query, location = _oauth_login_state(client)

    assert location.startswith("https://provider.example/authorize?")
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://testserver/auth/oauth/test/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert query["state"]


def test_oauth_callback_creates_user_and_returns_internal_jwt(
    client, db_session, configured_oauth, monkeypatch
):
    state, _query, _location = _oauth_login_state(client)
    seen = _stub_oauth_provider(
        monkeypatch,
        {
            "sub": "oauth-subject-1",
            "email": "oauth.patient@example.com",
            "email_verified": True,
            "name": "OAuth Patient",
        },
    )

    response = client.get(
        "/auth/oauth/test/callback",
        params={"code": "provider-code", "state": state},
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"
    assert seen["code"] == "provider-code"
    assert seen["redirect_uri"] == "http://testserver/auth/oauth/test/callback"
    assert seen["access_token"] == "provider-access-token"

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "oauth.patient@example.com"
    assert me_response.json()["role"] == "patient"

    db_session.expire_all()
    user = db_session.scalar(select(User).where(User.email == "oauth.patient@example.com"))
    assert user is not None
    assert user.hashed_password.startswith("oauth2_unusable$")
    identity = db_session.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "test",
            OAuthIdentity.subject == "oauth-subject-1",
        )
    )
    assert identity is not None
    assert identity.user_id == user.id

    password_response = client.post(
        "/auth/login",
        json={"email": "oauth.patient@example.com", "password": "Password123!"},
    )
    assert password_response.status_code == 401


def test_oauth_callback_links_existing_verified_email_without_changing_password_login(
    client, db_session, seeded_data, configured_oauth, monkeypatch
):
    state, _query, _location = _oauth_login_state(client)
    user_count_before = db_session.scalar(select(func.count(User.id)))
    _stub_oauth_provider(
        monkeypatch,
        {
            "sub": "oauth-subject-existing",
            "email": "patient@example.com",
            "email_verified": True,
            "name": "Patient One",
        },
    )

    response = client.get(
        "/auth/oauth/test/callback",
        params={"code": "provider-code", "state": state},
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["id"] == seeded_data["patient"].id
    assert me_response.json()["role"] == "patient"

    db_session.expire_all()
    assert db_session.scalar(select(func.count(User.id))) == user_count_before
    identity = db_session.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "test",
            OAuthIdentity.subject == "oauth-subject-existing",
        )
    )
    assert identity is not None
    assert identity.user_id == seeded_data["patient"].id

    password_response = client.post(
        "/auth/login",
        json={"email": "patient@example.com", "password": "Password123!"},
    )
    assert password_response.status_code == 200


def test_oauth_login_can_request_provider_role_for_new_user(
    client, configured_oauth, monkeypatch
):
    state, _query, _location = _oauth_login_state(client, role="provider")
    _stub_oauth_provider(
        monkeypatch,
        {
            "sub": "oauth-provider-subject",
            "email": "oauth.provider@example.com",
            "email_verified": True,
            "name": "OAuth Provider",
        },
    )

    response = client.get(
        "/auth/oauth/test/callback",
        params={"code": "provider-code", "state": state},
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["role"] == "provider"


def test_oauth_login_rejects_admin_self_registration(client, configured_oauth):
    response = client.get(
        "/auth/oauth/test/login",
        params={"role": "admin"},
        follow_redirects=False,
    )

    assert response.status_code == 422


def test_oauth_callback_rejects_unverified_email(client, configured_oauth, monkeypatch):
    state, _query, _location = _oauth_login_state(client)
    _stub_oauth_provider(
        monkeypatch,
        {
            "sub": "oauth-unverified-subject",
            "email": "unverified@example.com",
            "email_verified": False,
            "name": "Unverified User",
        },
    )

    response = client.get(
        "/auth/oauth/test/callback",
        params={"code": "provider-code", "state": state},
    )

    assert response.status_code == 403


def test_oauth_callback_rejects_invalid_state(client, configured_oauth):
    response = client.get(
        "/auth/oauth/test/callback",
        params={"code": "provider-code", "state": "invalid"},
    )

    assert response.status_code == 400


def test_oauth_login_requires_configured_provider(client):
    response = client.get("/auth/oauth/missing/login", follow_redirects=False)

    assert response.status_code == 503
