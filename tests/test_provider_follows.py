from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, OutboxEvent


def test_provider_follow_lifecycle(client, seeded_data, second_patient_headers):
    payload = {"provider_id": seeded_data["provider"].id}

    create_response = client.post("/provider-follows", headers=second_patient_headers, json=payload)
    assert create_response.status_code == 201
    follow_id = create_response.json()["id"]

    follows = client.get("/provider-follows/me", headers=second_patient_headers)
    assert follows.status_code == 200
    assert len(follows.json()) == 1
    assert follows.json()[0]["provider_id"] == seeded_data["provider"].id

    duplicate = client.post("/provider-follows", headers=second_patient_headers, json=payload)
    assert duplicate.status_code == 409

    delete_response = client.delete(f"/provider-follows/{follow_id}", headers=second_patient_headers)
    assert delete_response.status_code == 204
    assert client.get("/provider-follows/me", headers=second_patient_headers).json() == []

    recreate = client.post("/provider-follows", headers=second_patient_headers, json=payload)
    assert recreate.status_code == 201


def test_provider_only_patients_can_follow(client, seeded_data, provider_headers):
    response = client.post(
        "/provider-follows",
        headers=provider_headers,
        json={"provider_id": seeded_data["provider"].id},
    )
    assert response.status_code == 403


def test_provider_opening_slot_notifies_followers(
    client,
    seeded_data,
    provider_headers,
    second_patient_headers,
    patient_headers,
    db_session,
):
    follow_response = client.post(
        "/provider-follows",
        headers=second_patient_headers,
        json={"provider_id": seeded_data["provider"].id},
    )
    assert follow_response.status_code == 201

    start_at = seeded_data["second_slot"].end_at + timedelta(hours=1)
    create_slot = client.post(
        "/providers/me/availability",
        headers=provider_headers,
        json={
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(minutes=50)).isoformat(),
        },
    )
    assert create_slot.status_code == 201
    slot = create_slot.json()

    follower_notifications = client.get("/notifications/me", headers=second_patient_headers)
    assert follower_notifications.status_code == 200
    notification = follower_notifications.json()[0]
    assert notification["type"] == "slot_opened"
    assert notification["slot_id"] == slot["id"]
    assert notification["provider_id"] == seeded_data["provider"].id
    assert notification["provider_name"] == "Dr. Maya Chen"
    assert notification["appointment_request_id"] is None
    assert "opened a slot" in notification["message"]

    non_follower_notifications = client.get("/notifications/me", headers=patient_headers)
    assert non_follower_notifications.status_code == 200
    assert non_follower_notifications.json() == []

    event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "slot_opened"))
    assert event is not None
    assert event.user_id == seeded_data["second_patient"].id
    assert event.payload["event"] == "slot_opened"
    assert event.payload["slot_id"] == slot["id"]
    assert event.payload["provider_name"] == "Dr. Maya Chen"


def test_reopened_slot_notifies_provider_followers(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
):
    follow_response = client.post(
        "/provider-follows",
        headers=second_patient_headers,
        json={"provider_id": seeded_data["provider"].id},
    )
    assert follow_response.status_code == 201

    appointment = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    ).json()
    cancel = client.post(
        f"/appointment-requests/{appointment['id']}/cancel",
        headers=patient_headers,
        json={},
    )
    assert cancel.status_code == 200

    notifications = client.get("/notifications/me", headers=second_patient_headers)
    assert notifications.status_code == 200
    assert len(notifications.json()) == 1
    assert notifications.json()[0]["type"] == "slot_reopened"
    assert notifications.json()[0]["slot_id"] == seeded_data["open_slot"].id


def test_follower_and_matching_watcher_get_one_reopened_notification(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    follow_response = client.post(
        "/provider-follows",
        headers=second_patient_headers,
        json={"provider_id": seeded_data["provider"].id},
    )
    assert follow_response.status_code == 201
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

    appointment = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    ).json()
    cancel = client.post(
        f"/appointment-requests/{appointment['id']}/cancel",
        headers=patient_headers,
        json={},
    )
    assert cancel.status_code == 200

    notifications = db_session.scalars(select(Notification)).all()
    events = db_session.scalars(select(OutboxEvent)).all()
    assert len(notifications) == 1
    assert len(events) == 1
    assert notifications[0].user_id == seeded_data["second_patient"].id
    assert events[0].user_id == seeded_data["second_patient"].id
