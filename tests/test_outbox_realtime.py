import asyncio
from datetime import timedelta

from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.core.security import create_access_token
from app.enums import OutboxStatus
from app.models import OutboxEvent
from app.realtime.in_process import InProcessPublisher
from app.realtime.manager import ConnectionManager
from app.services.outbox_service import publish_pending_events


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    async def publish(self, event: OutboxEvent) -> str:
        self.events.append(event)
        return f"fake-stream-id-{event.id}"


class FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket used by ConnectionManager."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


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


def test_publish_pending_events_marks_event_published(
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


def test_in_process_publisher_delivers_payload_to_connected_user():
    payload = {"event": "slot_reopened", "user_id": 7, "notification_id": 1}

    async def scenario() -> str:
        cm = ConnectionManager()
        socket = FakeWebSocket()
        await cm.connect(7, socket)
        event = OutboxEvent(user_id=7, payload=payload)
        result = await InProcessPublisher(cm).publish(event)
        assert socket.sent == [payload]
        return result

    assert asyncio.run(scenario()) == "inprocess:1"


def test_in_process_publisher_noop_when_user_offline():
    async def scenario() -> str:
        cm = ConnectionManager()
        event = OutboxEvent(user_id=99, payload={"event": "slot_opened", "user_id": 99})
        return await InProcessPublisher(cm).publish(event)

    # Offline user: nothing delivered, but publish succeeds so the event is
    # marked published and the durable notification row carries the truth.
    assert asyncio.run(scenario()) == "inprocess:0"


def test_outbox_dispatch_delivers_through_in_process_publisher(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers)

    cm = ConnectionManager()
    socket = FakeWebSocket()

    async def scenario():
        await cm.connect(seeded_data["second_patient"].id, socket)
        return await publish_pending_events(db_session, InProcessPublisher(cm))

    result = asyncio.run(scenario())

    assert result.published == 1
    assert result.failed == 0
    assert len(socket.sent) == 1
    assert socket.sent[0]["event"] == "slot_reopened"
    assert socket.sent[0]["user_id"] == seeded_data["second_patient"].id

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent))
    assert event.status == OutboxStatus.published.value
    assert event.stream_message_id == "inprocess:1"


# --- Fix 1: malformed client frames must not drop / leak the connection -------


def test_websocket_survives_malformed_frame(client, patient_headers):
    token = patient_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws/notifications?token={token}") as websocket:
        websocket.send_text("this is not json")  # would crash a naive receive loop
        websocket.send_json({"event": "ping"})
        assert websocket.receive_json() == {"event": "pong"}


# --- Fix 2: the socket is closed once the access token expires -----------------


def test_websocket_closes_when_token_expires(client, seeded_data):
    patient = seeded_data["patient"]
    token = create_access_token(
        subject=patient.id,
        role=patient.role,
        expires_delta=timedelta(seconds=2),
    )
    with client.websocket_connect(f"/ws/notifications?token={token}") as websocket:
        try:
            websocket.receive_json()
            raise AssertionError("socket should close once the token expires")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


# --- Fix 3: exhausted retries become a terminal, visible dead-letter ----------


class AlwaysFailPublisher:
    async def publish(self, event: OutboxEvent) -> str:
        raise RuntimeError("broker down")


class FailOncePublisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, event: OutboxEvent) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient")
        return f"ok-{event.id}"


def test_outbox_event_dead_letters_after_max_attempts(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers)

    result = asyncio.run(
        publish_pending_events(db_session, AlwaysFailPublisher(), max_attempts=1)
    )
    assert result.published == 0
    assert result.failed == 1
    assert result.dead == 1

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent))
    assert event.status == OutboxStatus.dead.value
    assert event.attempt_count == 1
    assert "broker down" in event.last_error

    # Dead is terminal: a later poll must not re-attempt it.
    again = asyncio.run(
        publish_pending_events(db_session, AlwaysFailPublisher(), max_attempts=1)
    )
    assert again.failed == 0
    db_session.expire_all()
    assert db_session.scalar(select(OutboxEvent)).attempt_count == 1


def test_outbox_event_retries_after_transient_failure(
    client,
    seeded_data,
    patient_headers,
    second_patient_headers,
    db_session,
):
    create_reopened_slot_event(client, seeded_data, patient_headers, second_patient_headers)

    publisher = FailOncePublisher()
    first = asyncio.run(publish_pending_events(db_session, publisher))
    assert (first.published, first.failed, first.dead) == (0, 1, 0)

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent))
    assert event.status == OutboxStatus.failed.value
    assert event.attempt_count == 1

    # The next poll picks the failed-but-retryable event back up and publishes it.
    second = asyncio.run(publish_pending_events(db_session, publisher))
    assert second.published == 1

    db_session.expire_all()
    event = db_session.scalar(select(OutboxEvent))
    assert event.status == OutboxStatus.published.value
    assert event.attempt_count == 2
