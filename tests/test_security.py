def test_protected_endpoint_requires_token(client, seeded_data):
    response = client.get("/appointment-requests/me")
    assert response.status_code == 401


def test_invalid_token_returns_unauthorized(client, seeded_data):
    response = client.get("/appointment-requests/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401


def test_patient_cannot_use_provider_status_endpoint(client, seeded_data, patient_headers):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]
    response = client.patch(
        f"/appointment-requests/{appointment_id}/status",
        headers=patient_headers,
        json={"status": "confirmed"},
    )
    assert response.status_code == 403


def test_patient_cannot_cancel_other_patient_appointment(
    client, seeded_data, patient_headers, second_patient_headers
):
    create_response = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={"provider_id": seeded_data["provider"].id, "slot_id": seeded_data["open_slot"].id},
    )
    appointment_id = create_response.json()["id"]
    response = client.post(
        f"/appointment-requests/{appointment_id}/cancel",
        headers=second_patient_headers,
        json={},
    )
    assert response.status_code == 403


def test_hashed_password_never_exposed(client, seeded_data, patient_headers):
    responses = [
        client.get("/auth/me", headers=patient_headers),
        client.get("/providers"),
        client.get("/appointment-requests/me", headers=patient_headers),
    ]
    for response in responses:
        assert "hashed_password" not in response.text


def test_sql_like_filter_input_does_not_crash_or_bypass_filters(client, seeded_data):
    response = client.get("/providers", params={"city": "New York' OR 1=1 --"})
    assert response.status_code == 200
    assert response.json() == []


def test_invalid_ids_return_not_found(client, seeded_data, provider_headers):
    response = client.patch(
        "/appointment-requests/999999/status",
        headers=provider_headers,
        json={"status": "confirmed"},
    )
    assert response.status_code == 404
