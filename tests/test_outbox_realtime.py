import asyncio

from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.enums import OutboxStatus
from app.models import OutboxEvent
from app.services.outbox_service import publish_pending_events


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    async def publish(self, event: OutboxEvent) -> str:
        self.events.append(event)
        return f"fake-stream-id-{event.id}"


def create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers) -> None:
    watcher = client.post(
        "/slot-watchers",
        headers=second_patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "start_after": seeded_data["open_slot"].start_at.isoformat(),
            "start_before": seeded_data["second_slot"].start_at.isoformat(),
        },
    )
    assert watcher.status_code == 201

    appointment = client.post(
        "/appointment-requests",
        headers=patient_headers,
        json={
            "provider_id": seeded_data["provider"].id,
            "slot_id": seeded_data["open_slot"].id,
        },
    )
    assert appointment.status_code == 201

    cancel = client.post(
        f"/appointment-requests/{appointment.json()['id']}/cancel",
        headers=patient_headers,
        json={},
    )
    assert cancel.status_code == 200


def test_cancellation_creates_notification_outbox_event(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers)

    event = db_session.scalar(select(OutboxEvent))
    assert event is not None
    assert event.status == OutboxStatus.pending.value
    assert event.event_type == "slot_reopened"
    assert event.aggregate_type == "notification"
    assert event.user_id == seeded_data["second_patient"].id
    assert event.payload["event"] == "slot_reopened"
    assert event.payload["slot_id"] == seeded_data["open_slot"].id
    assert event.payload["provider_id"] == seeded_data["provider"].id
    assert event.payload["provider_name"] == "Dr. Maya Chen"


def test_outbox_worker_publishes_pending_event(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers)

    publisher = FakePublisher()
    result = asyncio.run(publish_pending_events(db_session, publisher))

    assert result.published == 1
    assert result.failed == 0
    assert len(publisher.events) == 1

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent))
    assert event.status == OutboxStatus.published.value
    assert event.attempt_count == 1
    assert event.stream_message_id == f"fake-stream-id-{event.id}"
    assert event.published_at is not None


def test_notifications_websocket_uses_fastapi_jwt(client, patient_headers):
    token = patient_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws/notifications?token={token}") as websocket:
        websocket.send_json({"event": "ping"})
        assert websocket.receive_json() == {"event": "pong"}


def test_notifications_websocket_rejects_invalid_token(client):
    try:
        with client.websocket_connect("/ws/notifications?token=invalid"):
            raise AssertionError("invalid token should not connect")
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
