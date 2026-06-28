import pytest
from sqlalchemy.exc import IntegrityError

from app.enums import AppointmentStatus, SlotStatus, UserRole
from app.models import AppointmentRequest, AvailabilitySlot, User


def test_duplicate_user_email_rejected(db_session, seeded_data):
    db_session.add(
        User(
            email="patient@example.com",
            full_name="Duplicate",
            role=UserRole.patient.value,
            hashed_password="hash",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_duplicate_active_appointment_for_same_slot_rejected(db_session, seeded_data):
    db_session.add(
        AppointmentRequest(
            patient_id=seeded_data["patient"].id,
            provider_id=seeded_data["provider"].id,
            slot_id=seeded_data["open_slot"].id,
            status=AppointmentStatus.pending.value,
        )
    )
    db_session.commit()
    db_session.add(
        AppointmentRequest(
            patient_id=seeded_data["second_patient"].id,
            provider_id=seeded_data["provider"].id,
            slot_id=seeded_data["open_slot"].id,
            status=AppointmentStatus.confirmed.value,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invalid_slot_status_rejected(db_session, seeded_data):
    db_session.add(
        AvailabilitySlot(
            provider_id=seeded_data["provider"].id,
            start_at=seeded_data["open_slot"].start_at,
            end_at=seeded_data["open_slot"].end_at,
            status="held",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_slot_end_must_be_after_start(db_session, seeded_data):
    db_session.add(
        AvailabilitySlot(
            provider_id=seeded_data["provider"].id,
            start_at=seeded_data["open_slot"].end_at,
            end_at=seeded_data["open_slot"].start_at,
            status=SlotStatus.open.value,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
