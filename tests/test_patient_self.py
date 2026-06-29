def _get_profile(client, headers):
    response = client.get("/patients/me/profile", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_patient_profile_patch_upserts_singleton(
    client, seeded_data, patient_headers, provider_headers
):
    missing_profile = _get_profile(client, patient_headers)
    assert missing_profile["profile"] is None

    create_response = client.patch(
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
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["preferred_name"] == "Patient"
    assert created["insurance_plan_id"] == seeded_data["aetna"].id

    update_response = client.patch(
        "/patients/me/profile",
        headers=patient_headers,
        json={"phone": "555-0101", "two_factor_enrolled": True},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["id"] == created["id"]
    assert updated["phone"] == "555-0101"
    assert updated["two_factor_enrolled"] is True

    empty_response = client.patch("/patients/me/profile", headers=patient_headers, json={})
    assert empty_response.status_code == 400

    provider_response = client.patch(
        "/patients/me/profile",
        headers=provider_headers,
        json={"preferred_name": "Wrong role"},
    )
    assert provider_response.status_code == 403


def test_patient_profile_returns_all_patient_form_sections(
    client, seeded_data, patient_headers, second_patient_headers
):
    profile_response = client.patch(
        "/patients/me/profile",
        headers=patient_headers,
        json={
            "preferred_name": "Patient",
            "legal_name": "Patient One",
            "insurance_plan_id": seeded_data["aetna"].id,
        },
    )
    assert profile_response.status_code == 200

    address_response = client.put(
        "/patients/me/addresses",
        headers=patient_headers,
        json=[
            {
                "label": "home",
                "line1": "100 Test Street",
                "city": "Boston",
                "state": "MA",
                "postal_code": "02108",
            }
        ],
    )
    assert address_response.status_code == 200

    contact_response = client.put(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json=[
            {
                "full_name": "Primary Contact",
                "relationship": "Friend",
                "phone": "555-0200",
            }
        ],
    )
    assert contact_response.status_code == 200

    accept_response = client.post(
        "/patients/me/consents/privacy-notice/accept",
        headers=patient_headers,
    )
    assert accept_response.status_code == 200

    account = _get_profile(client, patient_headers)
    assert account["profile"]["preferred_name"] == "Patient"
    assert [address["line1"] for address in account["addresses"]] == ["100 Test Street"]
    assert [contact["full_name"] for contact in account["emergency_contacts"]] == [
        "Primary Contact"
    ]
    privacy_notice = [
        consent for consent in account["consents"] if consent["form_key"] == "privacy-notice"
    ][0]
    assert privacy_notice["accepted"] is True

    other_account = _get_profile(client, second_patient_headers)
    assert other_account["profile"] is None
    assert other_account["addresses"] == []
    assert other_account["emergency_contacts"] == []
    other_privacy_notice = [
        consent
        for consent in other_account["consents"]
        if consent["form_key"] == "privacy-notice"
    ][0]
    assert other_privacy_notice["accepted"] is False


def test_patient_addresses_are_full_replacement_with_single_primary(client, patient_headers):
    replace_response = client.put(
        "/patients/me/addresses",
        headers=patient_headers,
        json=[
            {
                "label": "home",
                "line1": "100 Test Street",
                "city": "Boston",
                "state": "MA",
                "postal_code": "02108",
            },
            {
                "label": "school",
                "line1": "200 Test Avenue",
                "city": "Cambridge",
                "state": "MA",
                "postal_code": "02139",
                "source": "insurance",
                "is_primary": True,
            },
        ],
    )
    assert replace_response.status_code == 200
    addresses = replace_response.json()
    assert [address["label"] for address in addresses] == ["school", "home"]
    assert sum(address["is_primary"] for address in addresses) == 1

    conflict_response = client.put(
        "/patients/me/addresses",
        headers=patient_headers,
        json=[
            {
                "label": "home",
                "line1": "100 Test Street",
                "city": "Boston",
                "state": "MA",
                "postal_code": "02108",
                "is_primary": True,
            },
            {
                "label": "school",
                "line1": "200 Test Avenue",
                "city": "Cambridge",
                "state": "MA",
                "postal_code": "02139",
                "is_primary": True,
            },
        ],
    )
    assert conflict_response.status_code == 400

    clear_response = client.put("/patients/me/addresses", headers=patient_headers, json=[])
    assert clear_response.status_code == 200
    assert clear_response.json() == []
    assert _get_profile(client, patient_headers)["addresses"] == []


def test_emergency_contacts_are_full_replacement_with_priority_rules(client, patient_headers):
    replace_response = client.put(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json=[
            {
                "full_name": "Primary Contact",
                "relationship": "Friend",
                "phone": "555-0200",
            },
            {
                "full_name": "Secondary Contact",
                "relationship": "Sibling",
                "phone": "555-0202",
            },
        ],
    )
    assert replace_response.status_code == 200
    contacts = replace_response.json()
    assert [contact["priority"] for contact in contacts] == [1, 2]

    duplicate_priority_response = client.put(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json=[
            {
                "full_name": "Primary Contact",
                "phone": "555-0200",
                "priority": 1,
            },
            {
                "full_name": "Duplicate Priority",
                "phone": "555-0201",
                "priority": 1,
            },
        ],
    )
    assert duplicate_priority_response.status_code == 400

    too_many_response = client.put(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json=[
            {"full_name": "One", "phone": "555-0201"},
            {"full_name": "Two", "phone": "555-0202"},
            {"full_name": "Three", "phone": "555-0203"},
        ],
    )
    assert too_many_response.status_code == 400

    clear_response = client.put(
        "/patients/me/emergency-contacts",
        headers=patient_headers,
        json=[],
    )
    assert clear_response.status_code == 200
    assert clear_response.json() == []
    assert _get_profile(client, patient_headers)["emergency_contacts"] == []


def test_patient_consents_catalog_is_read_from_profile_and_acceptance_is_explicit(
    client, patient_headers, second_patient_headers
):
    account = _get_profile(client, patient_headers)
    consents = account["consents"]
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

    other_account = _get_profile(client, second_patient_headers)
    other_privacy = [
        consent
        for consent in other_account["consents"]
        if consent["form_key"] == "privacy-notice"
    ][0]
    assert other_privacy["accepted"] is False
