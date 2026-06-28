from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.enums import SlotStatus, UserRole  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AvailabilitySlot,
    InsurancePlan,
    ProviderProfile,
    Specialty,
    User,
)


@pytest.fixture()
def session_factory(tmp_path):
    database_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{database_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(session_factory) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(session_factory) -> Generator[TestClient, None, None]:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_data(db_session):
    patient = User(
        email="patient@example.com",
        full_name="Patient One",
        role=UserRole.patient.value,
        hashed_password=hash_password("Password123!"),
    )
    second_patient = User(
        email="patient2@example.com",
        full_name="Patient Two",
        role=UserRole.patient.value,
        hashed_password=hash_password("Password123!"),
    )
    provider_user = User(
        email="provider@example.com",
        full_name="Dr. Maya Chen",
        role=UserRole.provider.value,
        hashed_password=hash_password("Password123!"),
    )
    other_provider_user = User(
        email="other-provider@example.com",
        full_name="Dr. Other",
        role=UserRole.provider.value,
        hashed_password=hash_password("Password123!"),
    )
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        role=UserRole.admin.value,
        hashed_password=hash_password("Password123!"),
    )
    db_session.add_all([patient, second_patient, provider_user, other_provider_user, admin])
    db_session.flush()

    anxiety = Specialty(name="Anxiety")
    depression = Specialty(name="Depression")
    aetna = InsurancePlan(
        carrier_name="Aetna",
        plan_name="Open Choice PPO",
        display_name="Aetna Open Choice PPO",
    )
    cigna = InsurancePlan(
        carrier_name="Cigna",
        plan_name="LocalPlus",
        display_name="Cigna LocalPlus",
    )
    db_session.add_all([anxiety, depression, aetna, cigna])
    db_session.flush()

    provider = ProviderProfile(
        user_id=provider_user.id,
        display_name="Dr. Maya Chen",
        bio="Anxiety and depression specialist.",
        city="New York",
        state="NY",
        timezone="America/New_York",
        offers_virtual=True,
        offers_in_person=True,
    )
    provider.specialties.extend([anxiety, depression])
    provider.insurance_plans.append(aetna)

    other_provider = ProviderProfile(
        user_id=other_provider_user.id,
        display_name="Dr. Other",
        bio="Remote-only therapist.",
        city="Boston",
        state="MA",
        timezone="America/New_York",
        offers_virtual=True,
        offers_in_person=False,
    )
    other_provider.specialties.append(depression)
    other_provider.insurance_plans.append(cigna)
    db_session.add_all([provider, other_provider])
    db_session.flush()

    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=3)
    open_slot = AvailabilitySlot(
        provider_id=provider.id,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status=SlotStatus.open.value,
    )
    second_slot = AvailabilitySlot(
        provider_id=provider.id,
        start_at=start + timedelta(hours=1),
        end_at=start + timedelta(hours=1, minutes=50),
        status=SlotStatus.open.value,
    )
    booked_slot = AvailabilitySlot(
        provider_id=provider.id,
        start_at=start + timedelta(hours=2),
        end_at=start + timedelta(hours=2, minutes=50),
        status=SlotStatus.booked.value,
    )
    other_slot = AvailabilitySlot(
        provider_id=other_provider.id,
        start_at=start + timedelta(hours=3),
        end_at=start + timedelta(hours=3, minutes=50),
        status=SlotStatus.open.value,
    )
    db_session.add_all([open_slot, second_slot, booked_slot, other_slot])
    db_session.commit()

    return {
        "patient": patient,
        "second_patient": second_patient,
        "provider_user": provider_user,
        "other_provider_user": other_provider_user,
        "admin": admin,
        "provider": provider,
        "other_provider": other_provider,
        "anxiety": anxiety,
        "depression": depression,
        "aetna": aetna,
        "cigna": cigna,
        "open_slot": open_slot,
        "second_slot": second_slot,
        "booked_slot": booked_slot,
        "other_slot": other_slot,
    }


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def patient_headers(seeded_data):
    return auth_headers(seeded_data["patient"])


@pytest.fixture()
def second_patient_headers(seeded_data):
    return auth_headers(seeded_data["second_patient"])


@pytest.fixture()
def provider_headers(seeded_data):
    return auth_headers(seeded_data["provider_user"])


@pytest.fixture()
def other_provider_headers(seeded_data):
    return auth_headers(seeded_data["other_provider_user"])


@pytest.fixture()
def admin_headers(seeded_data):
    return auth_headers(seeded_data["admin"])
