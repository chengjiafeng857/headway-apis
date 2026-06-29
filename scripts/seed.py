from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.enums import SlotStatus, UserRole
from app.models import (
    AvailabilitySlot,
    CareType,
    ConsentForm,
    InsurancePlan,
    PatientAddress,
    PatientProfile,
    ProviderProfile,
    Specialty,
    StyleTag,
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

        warm = db.scalar(select(StyleTag).where(StyleTag.name == "Warm"))
        if warm is None:
            warm = StyleTag(name="Warm")
            db.add(warm)
        solution_oriented = db.scalar(
            select(StyleTag).where(StyleTag.name == "Solution-oriented")
        )
        if solution_oriented is None:
            solution_oriented = StyleTag(name="Solution-oriented")
            db.add(solution_oriented)

        therapy = db.scalar(select(CareType).where(CareType.name == "Therapy"))
        if therapy is None:
            therapy = CareType(name="Therapy")
            db.add(therapy)

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
                provider_type="therapist",
                credential="LMHC",
                quote="Collaborative, practical support for anxiety and mood concerns.",
                bio="Licensed therapist specializing in anxiety and depression.",
                city="New York",
                state="NY",
                timezone="America/New_York",
                years_experience=12,
                languages=["English"],
                license_states=["NY"],
                offers_virtual=True,
                offers_in_person=True,
                offers_free_consultation=True,
                accepting_new_clients=True,
            )
            provider.specialties.extend([anxiety, depression])
            provider.style_tags.extend([warm, solution_oriented])
            provider.care_types.append(therapy)
            provider.insurance_plans.append(aetna)
            db.add(provider)
            db.flush()
        if warm not in provider.style_tags:
            provider.style_tags.append(warm)
        if solution_oriented not in provider.style_tags:
            provider.style_tags.append(solution_oriented)
        if therapy not in provider.care_types:
            provider.care_types.append(therapy)
        if aetna not in provider.insurance_plans:
            provider.insurance_plans.append(aetna)

        patient_profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == patient.id))
        if patient_profile is None:
            db.add(
                PatientProfile(
                    user_id=patient.id,
                    preferred_name="Demo Patient",
                    legal_name="Demo Patient",
                    language="English",
                    insurance_plan_id=aetna.id,
                )
            )

        address_exists = db.scalar(
            select(PatientAddress.id).where(PatientAddress.patient_id == patient.id)
        )
        if address_exists is None:
            db.add(
                PatientAddress(
                    patient_id=patient.id,
                    label="home",
                    line1="100 Demo Street",
                    city="Boston",
                    state="MA",
                    postal_code="02108",
                    source="self_reported",
                    is_primary=True,
                )
            )

        for form_key, title in [
            ("privacy-notice", "Privacy notice"),
            ("consent-forms", "Consent forms"),
            ("hie-consent", "Health Information Exchange Consent"),
            ("telehealth-informed-consent", "Telehealth Informed Consent"),
            ("treat-and-payment-guarantee", "Consent to Treat & Guarantee of Payment"),
        ]:
            if db.scalar(select(ConsentForm.id).where(ConsentForm.form_key == form_key)) is None:
                db.add(
                    ConsentForm(
                        form_key=form_key,
                        title=title,
                        version="2026-01",
                        is_required=True,
                        is_active=True,
                    )
                )

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
