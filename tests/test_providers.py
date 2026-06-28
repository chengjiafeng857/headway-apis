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
    assert "Anxiety" in data["specialties"]

    missing_response = client.get("/providers/999999")
    assert missing_response.status_code == 404


def test_availability_returns_only_open_slots(client, seeded_data):
    response = client.get(f"/providers/{seeded_data['provider'].id}/availability")
    assert response.status_code == 200
    statuses = {slot["status"] for slot in response.json()}
    assert statuses == {"open"}
    slot_ids = {slot["id"] for slot in response.json()}
    assert seeded_data["booked_slot"].id not in slot_ids


def test_insurance_plans(client, seeded_data):
    response = client.get("/insurance-plans")
    assert response.status_code == 200
    assert {plan["display_name"] for plan in response.json()} == {
        "Aetna Open Choice PPO",
        "Cigna LocalPlus",
    }
