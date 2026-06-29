# Headway Care API

FastAPI backend inspired by Headway's therapy-provider search and scheduling flow.

## Features

- Manual JWT authentication
- Provider search by specialty, insurance, location, and care type
- Provider availability
- Appointment request creation
- Race-safe slot booking
- Appointment cancellation and slot reopening
- Provider/time-window watchers
- In-app reopened-slot notifications
- Transactional outbox events for reliable notification publishing
- Redis Streams fanout to a FastAPI WebSocket gateway
- SQLAlchemy models compatible with PostgreSQL/Supabase

## Local Run

```bash
uv sync
uv run python -m scripts.seed
uv run uvicorn app.main:app --reload
```

To use realtime WebSocket delivery locally, run Redis and the outbox worker in
separate terminals:

```bash
redis-server
uv run python -m scripts.outbox_worker
WEBSOCKET_REDIS_CONSUMER_ENABLED=true uv run uvicorn app.main:app --reload
```

The frontend connects with the existing FastAPI JWT:

```text
ws://localhost:8000/ws/notifications?token=<access-token>
```

Realtime messages are hints. After receiving a `slot_reopened` event, refresh
`GET /providers/{provider_id}/availability` before showing the slot as currently
bookable.

For a Supabase-backed run, copy `.env.example` to `.env`, replace every
placeholder, and initialize the schema from `supabase/schema.sql` before seeding.

For Docker:

```bash
cp .env.example .env
# edit .env before starting the container
docker compose up --build
```

Re-seed demo data any time:

```bash
uv run python -m scripts.seed
```

Demo accounts use password `Password123!`:

- `patient@example.com`
- `patient2@example.com`
- `provider@example.com`
- `admin@example.com`

## Test

```bash
uv run pytest
```

The test suite uses a file-based SQLite database for fast local unit tests. The booking code also uses PostgreSQL row locks when running against Supabase/Postgres.

## Realtime Architecture

Cancellation and decline flows insert `notifications` rows and `outbox_events`
rows in the same database transaction. The outbox worker publishes pending events
to Redis Streams, and the FastAPI WebSocket gateway consumes the stream and pushes
events to connected users.

Durable truth remains in the database:

- `notifications` stores what the user should be able to recover later.
- `outbox_events` stores what still needs to be published.
- Redis Streams handles multi-process event fanout.
- WebSocket delivery is best-effort and backed by `GET /notifications/me`.
