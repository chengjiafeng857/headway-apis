from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AppointmentRequest, AvailabilitySlot


def test_two_patients_cannot_book_same_slot_concurrently(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    def book_slot(headers):
        with TestClient(app) as local_client:
            return local_client.post(
                "/appointment-requests",
                headers=headers,
                json={
                    "provider_id": seeded_data["provider"].id,
                    "slot_id": seeded_data["open_slot"].id,
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(book_slot, [patient_headers, second_patient_headers]))

    assert sorted(statuses) == [201, 409]

    db_session.expire_all()
    appointments = db_session.scalars(
        select(AppointmentRequest).where(AppointmentRequest.slot_id == seeded_data["open_slot"].id)
    ).all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)

    assert len(appointments) == 1
    assert slot.status == "booked"
