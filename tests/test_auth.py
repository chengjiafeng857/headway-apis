from sqlalchemy import select

from app.models import User


def test_register_login_and_me(client):
    register_response = client.post(
        "/auth/register",
        json={
            "email": "new.patient@example.com",
            "password": "Password123!",
            "full_name": "New Patient",
            "role": "patient",
        },
    )
    assert register_response.status_code == 201
    assert "hashed_password" not in register_response.json()
    assert register_response.json()["role"] == "patient"

    login_response = client.post(
        "/auth/login",
        json={"email": "new.patient@example.com", "password": "Password123!"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "new.patient@example.com"
    assert "hashed_password" not in me_response.json()


def test_register_requires_explicit_role(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "missing.role@example.com",
            "password": "Password123!",
            "full_name": "Missing Role",
        },
    )
    assert response.status_code == 422


def test_register_rejects_admin_self_registration(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "admin.self@example.com",
            "password": "Password123!",
            "full_name": "Admin Self",
            "role": "admin",
        },
    )
    assert response.status_code == 422


def test_register_rejects_unknown_fields(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "extra.field@example.com",
            "password": "Password123!",
            "full_name": "Extra Field",
            "role": "patient",
            "is_active": False,
        },
    )
    assert response.status_code == 422


def test_duplicate_email_returns_conflict(client, seeded_data):
    response = client.post(
        "/auth/register",
        json={
            "email": "patient@example.com",
            "password": "Password123!",
            "full_name": "Duplicate",
            "role": "patient",
        },
    )
    assert response.status_code == 409


def test_invalid_login_returns_unauthorized(client, seeded_data):
    response = client.post(
        "/auth/login",
        json={"email": "patient@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_password_is_hashed(db_session, client):
    client.post(
        "/auth/register",
        json={
            "email": "hash.check@example.com",
            "password": "Password123!",
            "full_name": "Hash Check",
            "role": "patient",
        },
    )
    user = db_session.scalar(select(User).where(User.email == "hash.check@example.com"))
    assert user is not None
    assert user.hashed_password != "Password123!"
    assert user.hashed_password.startswith("pbkdf2_sha256$")
