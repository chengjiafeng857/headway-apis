def test_provider_search_filters(client, seeded_data):
    response = client.get("/providers", params={"specialty": "Anxiety"})
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) == 1
    assert providers[0]["display_name"] == "Dr. Maya Chen"

    response = client.get("/providers", params={"insurance_plan_id": seeded_data["aetna"].id})
    assert response.status_code == 200
    assert [provider["display_name"] for provider in response.json()] == ["Dr. Maya Chen"]

    response = client.get("/providers", params={"city": "Boston", "care_type": "virtual"})
    assert response.status_code == 200
    assert [provider["display_name"] for provider in response.json()] == ["Dr. Other"]


def test_provider_search_empty_result(client, seeded_data):
    response = client.get("/providers", params={"city": "Chicago"})
    assert response.status_code == 200
    assert response.json() == []


def test_invalid_pagination_returns_validation_error(client, seeded_data):
    response = client.get("/providers", params={"limit": 101})
    assert response.status_code == 422


def test_provider_detail_and_missing_provider(client, seeded_data):
    response = client.get(f"/providers/{seeded_data['provider'].id}")
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Dr. Maya Chen"
    assert data["provider_type"] == "therapist"
    assert data["credential"] == "LMHC"
    assert data["offers_free_consultation"] is True
    assert data["next_available_at"] is not None
    assert "Anxiety" in data["specialties"]
    assert "Warm" in data["style_tags"]
    assert "Therapy" in data["care_types"]

    missing_response = client.get("/providers/999999")
    assert missing_response.status_code == 404


def test_availability_returns_only_open_slots(client, seeded_data):
    response = client.get(f"/providers/{seeded_data['provider'].id}/availability")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["id"] == seeded_data["provider"].id
    statuses = {slot["status"] for slot in payload["slots"]}
    assert statuses == {"open"}
    slot_ids = {slot["id"] for slot in payload["slots"]}
    assert seeded_data["booked_slot"].id not in slot_ids


def test_insurance_plans(client, seeded_data):
    response = client.get("/insurance-plans")
    assert response.status_code == 200
    assert {plan["display_name"] for plan in response.json()} == {
        "Aetna Open Choice PPO",
        "Cigna LocalPlus",
    }


def test_specialties(client, seeded_data):
    response = client.get("/specialties")
    assert response.status_code == 200
    assert response.json() == [
        {"id": seeded_data["anxiety"].id, "name": "Anxiety"},
        {"id": seeded_data["depression"].id, "name": "Depression"},
    ]


def test_provider_search_headway_style_filters(client, seeded_data):
    response = client.get("/providers", params={"style": "Warm"})
    assert response.status_code == 200
    assert [provider["display_name"] for provider in response.json()] == ["Dr. Maya Chen"]

    response = client.get(
        "/providers",
        params={
            "provider_type": "psychiatric_mental_health_np",
            "session_mode": "virtual",
            "offers_free_consultation": False,
        },
    )
    assert response.status_code == 200
    assert [provider["display_name"] for provider in response.json()] == ["Dr. Other"]

    response = client.get(
        "/providers",
        params={"care_type": "virtual", "session_mode": "in_person"},
    )
    assert response.status_code == 400


def test_provider_can_manage_style_and_care_type_tags(client, seeded_data, provider_headers):
    style_response = client.put(
        "/providers/me/style-tags",
        headers=provider_headers,
        json={"style_tag_ids": [seeded_data["direct"].id]},
    )
    assert style_response.status_code == 200
    assert style_response.json()["style_tags"] == ["Direct"]

    care_type_response = client.put(
        "/providers/me/care-types",
        headers=provider_headers,
        json={"care_type_ids": [seeded_data["medication_management"].id]},
    )
    assert care_type_response.status_code == 200
    assert care_type_response.json()["care_types"] == ["Medication management"]


def test_registered_provider_can_create_profile(client):
    register_response = client.post(
        "/auth/register",
        json={
            "email": "new.provider@example.com",
            "password": "Password123!",
            "full_name": "New Provider",
            "role": "provider",
        },
    )
    assert register_response.status_code == 201
    assert register_response.json()["role"] == "provider"

    login_response = client.post(
        "/auth/login",
        json={"email": "new.provider@example.com", "password": "Password123!"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    invalid_profile = client.post(
        "/providers/me",
        headers=headers,
        json={
            "display_name": "New Provider",
            "provider_type": "therapist",
            "bio": "Available soon.",
            "city": "New York",
            "state": "NY",
            "timezone": "America/New_York",
            "offers_virtual": False,
            "offers_in_person": False,
        },
    )
    assert invalid_profile.status_code == 422

    profile_response = client.post(
        "/providers/me",
        headers=headers,
        json={
            "display_name": "New Provider",
            "provider_type": "therapist",
            "credential": "LICSW",
            "quote": "Supportive virtual therapy.",
            "bio": "Available soon.",
            "city": "New York",
            "state": "NY",
            "timezone": "America/New_York",
            "languages": ["English"],
            "license_states": ["NY"],
            "offers_virtual": True,
            "offers_in_person": False,
            "offers_free_consultation": True,
        },
    )
    assert profile_response.status_code == 201
    assert profile_response.json()["display_name"] == "New Provider"
    assert profile_response.json()["credential"] == "LICSW"
