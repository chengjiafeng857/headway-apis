from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.enums import SlotStatus, UserRole
from app.models import (
    AvailabilitySlot,
    InsurancePlan,
    ProviderProfile,
    Specialty,
    User,
)


def get_or_create_user(db, email: str, full_name: str, role: UserRole) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(
        email=email,
        full_name=full_name,
        role=role.value,
        hashed_password=hash_password("Password123!"),
    )
    db.add(user)
    db.flush()
    return user


def seed() -> None:
    if settings.auto_create_tables or settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        patient = get_or_create_user(db, "patient@example.com", "Demo Patient", UserRole.patient)
        get_or_create_user(db, "patient2@example.com", "Second Patient", UserRole.patient)
        provider_user = get_or_create_user(
            db, "provider@example.com", "Dr. Maya Chen", UserRole.provider
        )
        get_or_create_user(db, "admin@example.com", "Demo Admin", UserRole.admin)

        anxiety = db.scalar(select(Specialty).where(Specialty.name == "Anxiety"))
        if anxiety is None:
            anxiety = Specialty(name="Anxiety")
            db.add(anxiety)
        depression = db.scalar(select(Specialty).where(Specialty.name == "Depression"))
        if depression is None:
            depression = Specialty(name="Depression")
            db.add(depression)

        aetna = db.scalar(
            select(InsurancePlan).where(
                InsurancePlan.carrier_name == "Aetna",
                InsurancePlan.plan_name == "Open Choice PPO",
            )
        )
        if aetna is None:
            aetna = InsurancePlan(
                carrier_name="Aetna",
                plan_name="Open Choice PPO",
                display_name="Aetna Open Choice PPO",
            )
            db.add(aetna)

        provider = db.scalar(select(ProviderProfile).where(ProviderProfile.user_id == provider_user.id))
        if provider is None:
            provider = ProviderProfile(
                user_id=provider_user.id,
                display_name="Dr. Maya Chen",
                bio="Licensed therapist specializing in anxiety and depression.",
                city="New York",
                state="NY",
                timezone="America/New_York",
                offers_virtual=True,
                offers_in_person=True,
            )
            provider.specialties.extend([anxiety, depression])
            provider.insurance_plans.append(aetna)
            db.add(provider)
            db.flush()

        if not db.scalars(select(AvailabilitySlot).where(AvailabilitySlot.provider_id == provider.id)).first():
            start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
            for index in range(4):
                slot_start = start + timedelta(hours=index)
                db.add(
                    AvailabilitySlot(
                        provider_id=provider.id,
                        start_at=slot_start,
                        end_at=slot_start + timedelta(minutes=50),
                        status=SlotStatus.open.value,
                    )
                )

        # Keep variable referenced so linters know this account is intentionally seeded.
        assert patient.email == "patient@example.com"
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
