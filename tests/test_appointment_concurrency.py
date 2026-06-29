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

    # Exactly one booking wins; the other must fail with a client error. On
    # Postgres the loser is serialized by the row lock and returns 409. On SQLite
    # (used for these fast unit tests) row locks are a no-op and coarse file
    # locking can make the loser's slot read come back empty, surfacing as 404.
    # Either way the invariant below — one appointment, slot booked — must hold.
    success = [code for code in statuses if code == 201]
    conflict = [code for code in statuses if code in (404, 409)]
    assert len(success) == 1, statuses
    assert len(conflict) == 1, statuses

    db_session.expire_all()
    appointments = db_session.scalars(
        select(AppointmentRequest).where(AppointmentRequest.slot_id == seeded_data["open_slot"].id)
    ).all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)

    assert len(appointments) == 1
    assert slot.status == "booked"
