from sqlalchemy import select

from app.enums import AppointmentStatus, SlotStatus
from app.models import AppointmentRequest, AvailabilitySlot, OutboxEvent


def test_patient_books_open_slot(client, seeded_data, patient_headers, db_session):
    response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "slot_id": seeded_data["open_slot"].id,
            "reason": "Initial consultation",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == AppointmentStatus.pending.value

    db_session.expire_all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)
    assert slot.status == SlotStatus.booked.value


def test_booking_same_slot_twice_returns_conflict(
    client, seeded_data, patient_headers, second_patient_headers
):
    first = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    assert first.status_code == 201

    second = client.post(
        "/appointment-requests",
        headers=second_patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    assert second.status_code == 409


def test_booking_slot_provider_mismatch_returns_bad_request(client, seeded_data, patient_headers):
    response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={
            "provider_id": seeded_data["other_provider"].id,
            "slot_id": seeded_data["open_slot"].id,
        },
    )
    assert response.status_code == 400


def test_patient_can_view_only_own_appointments(
    client, seeded_data, patient_headers, second_patient_headers
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    assert create_response.status_code == 201

    own_response = client.get("/appointment-requests/me", headers=patient_headers)
    assert own_response.status_code == 200
    assert len(own_response.json()) == 1

    other_response = client.get("/appointment-requests/me", headers=second_patient_headers)
    assert other_response.status_code == 200
    assert other_response.json() == []


def test_provider_confirms_own_appointment(client, seeded_data, patient_headers, provider_headers):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    update_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "confirmed"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "confirmed"


def test_provider_cannot_update_other_provider_appointment(
    client, seeded_data, patient_headers, other_provider_headers
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    update_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=other_provider_headers,
        json={"status": "confirmed"},
    )
    assert update_response.status_code == 403


def test_admin_can_update_any_appointment(client, seeded_data, patient_headers, admin_headers):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    update_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=admin_headers,
        json={"status": "confirmed"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "confirmed"


def test_cancel_reopens_slot_and_makes_it_available(
    client, seeded_data, patient_headers, second_patient_headers, db_session
):
    watcher_response = client.post(
        "/slot-watchers",
        headers=second_patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "start_after": seeded_data["open_slot"].start_at.isoformat(),
            "start_before": seeded_data["second_slot"].start_at.isoformat(),
        },
    )
    assert watcher_response.status_code == 201

    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    cancel_response = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=patient_headers,
        json={"reason": "Need to reschedule"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    db_session.expire_all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)
    assert slot.status == SlotStatus.open.value

    availability_response = client.get(f"/providers/{seeded_data['provider'].id}/availability")
    assert seeded_data["open_slot"].id in {
        slot["id"] for slot in availability_response.json()["slots"]
    }

    notification_response = client.get("/notifications/me", headers=second_patient_headers)
    assert notification_response.status_code == 200
    notifications = notification_response.json()
    assert len(notifications) == 1
    assert notifications[0]["type"] == "slot_reopened"

    patient_notifications = client.get("/notifications/me", headers=patient_headers)
    assert patient_notifications.status_code == 200
    assert patient_notifications.json() == []


def test_provider_cancel_notifies_booked_patient_and_reopen_watchers(
    client,
    seeded_data,
    patient_headers,
    provider_headers,
    second_patient_headers,
    db_session,
):
    watcher_response = client.post(
        "/slot-watchers",
        headers=second_patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "start_after": seeded_data["open_slot"].start_at.isoformat(),
            "start_before": seeded_data["second_slot"].start_at.isoformat(),
        },
    )
    assert watcher_response.status_code == 201

    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    assert create_response.status_code == 201
    appointment_id = create_response.json()["id"]

    cancel_response = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=provider_headers,
        json={"reason": "Provider unavailable"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    patient_notifications = client.get("/notifications/me", headers=patient_headers)
    assert patient_notifications.status_code == 200
    patient_notification = patient_notifications.json()[0]
    assert patient_notification["type"] == "appointment_cancelled"
    assert patient_notification["appointment_request_id"] == appointment_id
    assert patient_notification["user_id"] == seeded_data["patient"].id
    assert "was cancelled" in patient_notification["message"]

    watcher_notifications = client.get("/notifications/me", headers=second_patient_headers)
    assert watcher_notifications.status_code == 200
    watcher_notification = watcher_notifications.json()[0]
    assert watcher_notification["type"] == "slot_reopened"
    assert watcher_notification["appointment_request_id"] == appointment_id
    assert watcher_notification["user_id"] == seeded_data["second_patient"].id

    db_session.expire_all()
    events = db_session.scalars(
        select(OutboxEvent).order_by(OutboxEvent.user_id, OutboxEvent.event_type)
    ).all()
    assert {(event.user_id, event.event_type) for event in events} == {
        (seeded_data["patient"].id, "appointment_cancelled"),
        (seeded_data["second_patient"].id, "slot_reopened"),
    }


def test_provider_decline_notifies_booked_patient(
    client,
    seeded_data,
    patient_headers,
    provider_headers,
    db_session,
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    assert create_response.status_code == 201
    appointment_id = create_response.json()["id"]

    decline_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "declined", "reason": "Not a fit"},
    )
    assert decline_response.status_code == 200

    patient_notifications = client.get("/notifications/me", headers=patient_headers)
    assert patient_notifications.status_code == 200
    assert len(patient_notifications.json()) == 1
    notification = patient_notifications.json()[0]
    assert notification["type"] == "appointment_declined"
    assert notification["appointment_request_id"] == appointment_id
    assert "was declined" in notification["message"]

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.user_id == seeded_data["patient"].id))
    assert event is not None
    assert event.event_type == "appointment_declined"
    assert event.payload["event"] == "appointment_declined"
    assert event.payload["notification_id"] == notification["id"]


def test_cancel_already_cancelled_returns_conflict(client, seeded_data, patient_headers):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]
    first_cancel = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=patient_headers,
        json={},
    )
    assert first_cancel.status_code == 200
    second_cancel = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=patient_headers,
        json={},
    )
    assert second_cancel.status_code == 409


def test_decline_reopens_slot(client, seeded_data, patient_headers, provider_headers, db_session):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    decline_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "declined"},
    )
    assert decline_response.status_code == 200

    db_session.expire_all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)
    appointment = db_session.scalar(select(AppointmentRequest).where(AppointmentRequest.id == appointment_id))
    assert slot.status == SlotStatus.open.value
    assert appointment.status == AppointmentStatus.declined.value


def test_declined_appointment_cannot_be_confirmed_after_slot_reopens(
    client, seeded_data, patient_headers, provider_headers, db_session
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    decline_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "declined"},
    )
    assert decline_response.status_code == 200

    confirm_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "confirmed"},
    )
    assert confirm_response.status_code == 409

    db_session.expire_all()
    slot = db_session.get(AvailabilitySlot, seeded_data["open_slot"].id)
    appointment = db_session.scalar(select(AppointmentRequest).where(AppointmentRequest.id == appointment_id))
    assert slot.status == SlotStatus.open.value
    assert appointment.status == AppointmentStatus.declined.value


def test_declined_appointment_cannot_be_cancelled_again(
    client, seeded_data, patient_headers, provider_headers
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    decline_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "declined"},
    )
    assert decline_response.status_code == 200

    cancel_response = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=patient_headers,
        json={},
    )
    assert cancel_response.status_code == 409


def test_pending_appointment_cannot_be_completed_directly(
    client, seeded_data, patient_headers, provider_headers
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]

    complete_response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=provider_headers,
        json={"status": "completed"},
    )
    assert complete_response.status_code == 409
