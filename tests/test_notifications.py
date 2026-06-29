def test_watcher_lifecycle_and_mark_notification_read(
    client, seeded_data, patient_headers, second_patient_headers
):
    create_watcher = client.post(
        "/slot-watchers",
        headers=second_patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "start_after": seeded_data["open_slot"].start_at.isoformat(),
            "start_before": seeded_data["second_slot"].start_at.isoformat(),
        },
    )
    assert create_watcher.status_code == 201

    watchers = client.get("/slot-watchers/me", headers=second_patient_headers)
    assert watchers.status_code == 200
    assert len(watchers.json()) == 1

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
    notification = notifications.json()[0]
    assert notification["is_read"] is False
    assert notification["slot_id"] == seeded_data["open_slot"].id
    assert notification["provider_id"] == seeded_data["provider"].id
    assert notification["provider_name"] == "Dr. Maya Chen"
    assert notification["start_at"] == seeded_data["open_slot"].start_at.isoformat().replace("+00:00", "Z")
    assert notification["end_at"] == seeded_data["open_slot"].end_at.isoformat().replace("+00:00", "Z")

    read_response = client.patch(
        f"/notifications/{notification['id']}/read",
        headers=second_patient_headers,
    )
    assert read_response.status_code == 200
    assert read_response.json()["is_read"] is True
    assert read_response.json()["provider_id"] == seeded_data["provider"].id


def test_non_matching_watcher_receives_no_notification(
    client, seeded_data, patient_headers, second_patient_headers
):
    response = client.post(
        "/slot-watchers",
        headers=second_patient_headers,
        json={
            "provider_id": seeded_data["other_provider"].id,
            "start_after": seeded_data["open_slot"].start_at.isoformat(),
            "start_before": seeded_data["second_slot"].start_at.isoformat(),
        },
    )
    assert response.status_code == 201

    appointment = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    ).json()
    client.post(
        f"/appointment-requests/{appointment['id']}/cancel",
        headers=patient_headers,
        json={},
    )

    notifications = client.get("/notifications/me", headers=second_patient_headers)
    assert notifications.status_code == 200
    assert notifications.json() == []


def test_duplicate_active_watcher_returns_conflict(client, seeded_data, second_patient_headers):
    payload = {
        "provider_id": seeded_data["provider"].id,
        "start_after": seeded_data["open_slot"].start_at.isoformat(),
        "start_before": seeded_data["second_slot"].start_at.isoformat(),
    }
    assert client.post("/slot-watchers", headers=second_patient_headers, json=payload).status_code == 201
    assert client.post("/slot-watchers", headers=second_patient_headers, json=payload).status_code == 409
