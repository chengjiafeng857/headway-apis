def test_patient_profile_self_service(client, seeded_data, patient_headers, provider_headers):
    missing_response = client.get("/patients/me/profile", headers=patient_headers)
    assert missing_response.status_code == 200
    assert missing_response.json()["profile"] is None

    create_response = client.post(
        "/patients/me/profile",
        headers=patient_headers,
        json={
            "preferred_name": "Patient",
            "legal_name": "Patient One",
            "pronouns": "they/them",
            "phone": "555-0100",
            "gender": "Non-binary",
            "gender_status": "Provided",
            "ethnicity": "Not provided",
            "language": "English",
            "insurance_plan_id": seeded_data["aetna"].id,
        },
    )
    assert create_response.status_code == 201
    data = create_response.json()
    assert data["preferred_name"] == "Patient"
    assert data["insurance_plan_id"] == seeded_data["aetna"].id

    duplicate_response = client.post(
        "/patients/me/profile",
        headers=patient_headers,
        json={"preferred_name": "Duplicate"},
    )
    assert duplicate_response.status_code == 409

    update_response = client.patch(
        "/patients/me/profile",
        headers=patient_headers,
        json={"phone": "555-0101", "two_factor_enrolled": True},
    )
    assert update_response.status_code == 200
    assert update_response.json()["phone"] == "555-0101"
    assert update_response.json()["two_factor_enrolled"] is True

    provider_response = client.post(
        "/patients/me/profile",
        headers=provider_headers,
        json={"preferred_name": "Wrong role"},
    )
    assert provider_response.status_code == 403


def test_patient_profile_returns_all_patient_form_sections(
    client, seeded_data, patient_headers, second_patient_headers
):
    profile_response = client.post(
        "/patients/me/profile",
        headers=patient_headers,
        json={
            "preferred_name": "Patient",
            "legal_name": "Patient One",
            "insurance_plan_id": seeded_data["aetna"].id,
        },
    )
    assert profile_response.status_code == 201

    address_response = client.post(
        "/patients/me/addresses",
        headers=patient_headers,
        json={
            "label": "home",
            "line1": "100 Test Street",
            "city": "Boston",
            "state": "MA",
            "postal_code": "02108",
        },
    )
    assert address_response.status_code == 201

    contact_response = client.post(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json={
            "full_name": "Primary Contact",
            "relationship": "Friend",
            "phone": "555-0200",
            "priority": 1,
        },
    )
    assert contact_response.status_code == 201

    accept_response = client.post(
        "/patients/me/consents/privacy-notice/accept",
        headers=patient_headers,
    )
    assert accept_response.status_code == 200

    info_response = client.get("/patients/me/profile", headers=patient_headers)
    assert info_response.status_code == 200
    info_forms = info_response.json()
    assert info_forms["profile"]["preferred_name"] == "Patient"
    assert [address["line1"] for address in info_forms["addresses"]] == ["100 Test Street"]
    assert [contact["full_name"] for contact in info_forms["emergency_contacts"]] == [
        "Primary Contact"
    ]
    privacy_notice = [
        consent for consent in info_forms["consents"] if consent["form_key"] == "privacy-notice"
    ][0]
    assert privacy_notice["accepted"] is True

    other_patient_response = client.get("/patients/me/profile", headers=second_patient_headers)
    assert other_patient_response.status_code == 200
    other_info_forms = other_patient_response.json()
    assert other_info_forms["profile"] is None
    assert other_info_forms["addresses"] == []
    assert other_info_forms["emergency_contacts"] == []
    other_privacy_notice = [
        consent
        for consent in other_info_forms["consents"]
        if consent["form_key"] == "privacy-notice"
    ][0]
    assert other_privacy_notice["accepted"] is False


def test_patient_addresses_keep_single_primary(client, patient_headers):
    first_response = client.post(
        "/patients/me/addresses",
        headers=patient_headers,
        json={
            "label": "home",
            "line1": "100 Test Street",
            "city": "Boston",
            "state": "MA",
            "postal_code": "02108",
            "is_primary": False,
        },
    )
    assert first_response.status_code == 201
    first_address = first_response.json()
    assert first_address["is_primary"] is True

    second_response = client.post(
        "/patients/me/addresses",
        headers=patient_headers,
        json={
            "label": "school",
            "line1": "200 Test Avenue",
            "city": "Cambridge",
            "state": "MA",
            "postal_code": "02139",
            "source": "insurance",
            "is_primary": True,
        },
    )
    assert second_response.status_code == 201
    second_address = second_response.json()
    assert second_address["is_primary"] is True

    list_response = client.get("/patients/me/addresses", headers=patient_headers)
    assert list_response.status_code == 200
    addresses = list_response.json()
    assert [address["id"] for address in addresses] == [second_address["id"], first_address["id"]]
    assert sum(address["is_primary"] for address in addresses) == 1


def test_emergency_contacts_are_limited_to_two(client, patient_headers):
    first_response = client.post(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json={
            "full_name": "Primary Contact",
            "relationship": "Friend",
            "phone": "555-0200",
            "priority": 1,
        },
    )
    assert first_response.status_code == 201

    duplicate_priority_response = client.post(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json={
            "full_name": "Duplicate Priority",
            "phone": "555-0201",
            "priority": 1,
        },
    )
    assert duplicate_priority_response.status_code == 409

    second_response = client.post(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json={
            "full_name": "Secondary Contact",
            "relationship": "Sibling",
            "phone": "555-0202",
            "priority": 2,
        },
    )
    assert second_response.status_code == 201

    third_response = client.post(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json={
            "full_name": "Third Contact",
            "phone": "555-0203",
            "priority": 2,
        },
    )
    assert third_response.status_code == 409


def test_patient_consents_catalog_and_acceptance(client, patient_headers, second_patient_headers):
    list_response = client.get("/patients/me/consents", headers=patient_headers)
    assert list_response.status_code == 200
    consents = list_response.json()
    assert {consent["form_key"] for consent in consents} == {
        "privacy-notice",
        "telehealth-informed-consent",
    }
    assert all(consent["accepted"] is False for consent in consents)

    accept_response = client.post(
        "/patients/me/consents/privacy-notice/accept",
        headers=patient_headers,
    )
    assert accept_response.status_code == 200
    accepted = accept_response.json()
    assert accepted["form_key"] == "privacy-notice"
    assert accepted["accepted"] is True
    assert accepted["accepted_at"] is not None

    other_patient_response = client.get("/patients/me/consents", headers=second_patient_headers)
    assert other_patient_response.status_code == 200
    other_privacy = [
        consent
        for consent in other_patient_response.json()
        if consent["form_key"] == "privacy-notice"
    ][0]
    assert other_privacy["accepted"] is False
