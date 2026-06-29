# Headway Care API

FastAPI backend inspired by Headway's therapy-provider search and scheduling flow.

## Features

- Manual JWT authentication
- Provider search by specialty, insurance, location, and care type
- Headway-style provider cards with provider type, credential, profile quote,
  style tags, care types, free-consultation flag, and next available slot
- Patient account forms for profile details, addresses, emergency contacts, and
  consent acknowledgements
- Provider availability
- Appointment request creation
- Race-safe slot booking
- Appointment cancellation and slot reopening
- Provider follows
- Provider/time-window watchers
- In-app slot-opened and reopened-slot notifications
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

Realtime messages are hints. After receiving a `slot_opened` or `slot_reopened`
event, refresh `GET /providers/{provider_id}/availability` before showing the
slot as currently bookable.

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

## API Notes

`POST /auth/register` requires an explicit `role`. Public self-registration
allows `patient` and `provider`; `admin` accounts must be provisioned through a
trusted path.

Patient-owned account data is exposed under `/patients/me`:

- `GET /patients/me/profile` for the aggregate account forms payload
- `PATCH /patients/me/profile` to partially update the singleton patient profile,
  creating it when missing
- `PUT /patients/me/addresses` to replace the full address list
- `PUT /patients/me/emergency-contacts` to replace the full emergency contact
  list
- `POST /patients/me/consents/{form_key}/accept` for explicit consent
  acceptance

Provider-owned profile enrichment is exposed under `/providers/me` with
taxonomy updates for `/specialties`, `/insurance-plans`, `/style-tags`, and
`/care-types`. Public provider search supports Headway-style filters such as
`style`, `provider_type`, `gender`, `ethnicity`, `offers_free_consultation`,
`accepting_new_clients`, `available_before`, and `session_mode`.

## Realtime Architecture

Provider slot creation, appointment cancellation, and appointment decline flows
insert `notifications` rows and `outbox_events` rows in the same database
transaction. The outbox worker publishes pending events to Redis Streams, and the
FastAPI WebSocket gateway consumes the stream and pushes events to connected
users.

Durable truth remains in the database:

- `notifications` stores what the user should be able to recover later.
- `outbox_events` stores what still needs to be published.
- Redis Streams handles multi-process event fanout.
- WebSocket delivery is best-effort and backed by `GET /notifications/me`.
