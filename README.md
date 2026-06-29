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
- In-process outbox dispatcher pushing events to a FastAPI WebSocket gateway
- SQLAlchemy models compatible with PostgreSQL/Supabase

## Local Run

```bash
uv sync
uv run python -m scripts.seed
uv run uvicorn app.main:app --reload
```

To use realtime WebSocket delivery locally, run the API with the in-process
outbox dispatcher enabled — no Redis, no separate worker:

```bash
REALTIME_DISPATCH_ENABLED=true uv run uvicorn app.main:app --reload
```

The frontend connects with the existing FastAPI JWT:

```text
ws://localhost:8000/ws/notifications?token=<access-token>
```

WebSocket delivery is **best-effort**: an event fired while a user has no live
socket (offline, page reload, flaky network) is dropped and never replayed over
the socket. Clients **must** reconcile on every (re)connect:

1. On connect, call `GET /notifications/me?is_read=false` and render the backlog.
2. Dedupe live socket events against that backlog by `notification_id` (events
   and REST rows share the same id).

Realtime messages are also hints about availability. After a `slot_opened` or
`slot_reopened` event, refresh `GET /providers/{provider_id}/availability`
before showing the slot as currently bookable.

For a Supabase-backed run, copy `.env.example` to `.env`, replace every
placeholder, and initialize the schema from `supabase/schema.sql` before seeding.

For Docker:

```bash
cp .env.example .env
# edit .env before starting the container
docker compose up --build
```

## CI/CD

Pushes to `dev` run `.github/workflows/deploy-dev.yml`.

The workflow:

1. installs dependencies with `uv sync --locked`
2. runs `uv run pytest`
3. SSHes to the VPS
4. resets `/home/ec2-user/headway-apis` to `origin/dev`
5. rebuilds the Docker image
6. recreates the `api` service and checks `/health`

Configure these GitHub repository secrets:

- `VPS_HOST`: EC2 public DNS or IP
- `VPS_USER`: `ec2-user`
- `VPS_SSH_PRIVATE_KEY`: private key that can SSH to the VPS
- `VPS_PORT`: optional, defaults to `22`

Keep app secrets in `/home/ec2-user/headway-apis/.env` on the VPS. Do not add
Supabase credentials or JWT secrets to GitHub Actions.

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
transaction. An in-process dispatcher (`app/realtime/dispatcher.py`), started in
the app lifespan when `REALTIME_DISPATCH_ENABLED=true`, polls the outbox and
hands each payload to the in-memory `ConnectionManager`, which pushes it to the
connected user's WebSocket sockets.

Durable truth remains in the database:

- `notifications` stores what the user should be able to recover later.
- `outbox_events` stores what still needs to be published.
- The dispatcher delivers to local sockets; offline users are skipped.
- WebSocket delivery is best-effort and backed by `GET /notifications/me`
  (clients reconcile on (re)connect, deduping by `notification_id`).

This is single-instance by design: delivery targets in-memory sockets, so the
dispatcher must run inside the API process. Scaling to multiple instances later
means reintroducing a broker (Redis pub/sub for fan-out, or Streams) between the
outbox and the gateways — the `OutboxPublisher` protocol is the seam for that.
