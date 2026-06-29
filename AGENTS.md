# AGENTS.md — Headway Care API

System guide for humans and AI agents working in this repository. It describes
what the system does, how it is structured, and the decisions and constraints
that are not obvious from any single file. Keep it current when behavior changes.

---

## 1. What this is

A FastAPI backend inspired by Headway's therapy-provider search and scheduling
flow. Core capabilities:

- Manual JWT authentication with `patient` / `provider` / `admin` roles.
- Provider search (specialty, insurance, location, care type, style, etc.) with
  Headway-style provider cards and "next available slot".
- Patient self-service account data: profile, addresses, emergency contacts,
  consent acknowledgements.
- Provider self-service: profile, availability slots, and taxonomy assignments.
- Appointment requests with **race-safe booking** and a status state machine.
- Appointment cancellation/decline that **reopens the slot** and alerts watchers.
- **Provider follows** and **time-window slot watchers** as notification sources.
- In-app `slot_opened` / `slot_reopened` notifications, persisted durably.
- A **transactional outbox** feeding an **in-process realtime dispatcher** that
  pushes events to connected WebSocket clients. (No Redis — see §7.)

## 2. Tech stack

- Python ≥ 3.11, FastAPI, Starlette WebSockets, Uvicorn.
- SQLAlchemy 2.0 (sync ORM, `DeclarativeBase`, sync `Session`).
- Database: SQLite by default (`sqlite:///./headway.db`); PostgreSQL / Supabase
  in production. Hand-written DDL also in `supabase/schema.sql`.
- Auth/crypto: hand-rolled HS256 JWT and PBKDF2-SHA256 password hashing in
  `app/core/security.py` (no external JWT/passlib dependency).
- Tooling: `uv` for env/deps, `pytest` + `pytest-cov` for tests.

## 3. Layout & layering

```
app/
  main.py            # create_app(), router wiring, lifespan (starts dispatcher)
  dependencies.py    # get_current_user, require_roles(*) auth dependencies
  enums.py           # UserRole, SlotStatus, AppointmentStatus, NotificationType, OutboxStatus
  models.py          # all SQLAlchemy ORM models (one Base)
  schemas.py         # Pydantic request/response schemas
  core/
    config.py        # Settings dataclass, env loading, prod guards
    database.py      # engine, SessionLocal, get_db(), Base
    security.py      # JWT encode/decode, password hash/verify
  routers/           # HTTP endpoints, thin — delegate to services
    auth, providers, patient_self, provider_self,
    appointments, follows, watchers, notifications
  services/          # business logic + DB access (the real work lives here)
    auth_service, authorization, provider_service, patient_service,
    appointment_service, follow_service, watcher_service,
    notification_service, outbox_service
  realtime/
    manager.py       # ConnectionManager: in-memory user_id -> {WebSocket}
    routes.py        # /ws/notifications WebSocket endpoint
    in_process.py    # InProcessPublisher (OutboxPublisher impl -> ConnectionManager)
    dispatcher.py    # dispatch_outbox_events(): in-process outbox poller
scripts/seed.py      # demo data seeding
supabase/schema.sql  # canonical Postgres DDL (mirrors models.py)
tests/               # pytest suite (SQLite-backed)
```

**Layering rule:** routers are thin (parse/validate, call a service, return).
Business logic and **all** DB access live in `services/`. Routers must not
contain queries. Services raise `fastapi.HTTPException` for client-facing errors.

## 4. Configuration (`app/core/config.py`)

`Settings` is a frozen dataclass populated from env vars (loaded from `.env` at
repo root; real process env wins over the file). Key vars:

| Env var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./headway.db` | SQLAlchemy URL |
| `JWT_SECRET_KEY` | `change-me-in-production` | HS256 signing key |
| `JWT_EXPIRE_MINUTES` | `60` | Access-token lifetime |
| `AUTO_CREATE_TABLES` | `false` | `create_all()` on startup (dev only) |
| `ENVIRONMENT` | `development` | `production` enables guards |
| `REALTIME_DISPATCH_ENABLED` | `false` | Start the in-process outbox dispatcher |
| `OUTBOX_BATCH_SIZE` | `50` | Max events drained per poll |
| `OUTBOX_POLL_SECONDS` | `1.0` | Dispatcher poll interval |
| `DB_ECHO` / `DB_ECHO_POOL` | `false` | SQL / pool logging |

**Production guard:** `__post_init__` refuses to start when
`ENVIRONMENT=production` and `JWT_SECRET_KEY` is still the placeholder.

## 5. Authentication & authorization

- **JWT** (`core/security.py`): HS256, payload `{sub: <user id>, role, iat, exp}`.
  `decode_access_token` verifies signature and rejects expired tokens.
- **Passwords:** PBKDF2-SHA256, 600k iterations, stored as
  `pbkdf2_sha256$<iters>$<salt>$<digest>`; verified with `secrets.compare_digest`.
- **`get_current_user`** (`dependencies.py`): `HTTPBearer`, decodes the token,
  loads the active `User`. Returns 401 on missing/invalid/expired token or
  inactive/unknown user.
- **`require_roles(*roles)`**: dependency factory → 403 if role not allowed.
- **Service-level checks** (`services/authorization.py`): `ensure_patient`,
  `ensure_provider`, `get_provider_profile_for_user`, `can_manage_appointment`
  (admin always; provider only for their own appointments).
- **Registration policy:** `POST /auth/register` requires an explicit `role`;
  public self-registration allows `patient`/`provider` only — `admin` must be
  provisioned through a trusted path.

## 6. Data model (`app/models.py` ↔ `supabase/schema.sql`)

One `Base`; the ORM and the SQL file define the same tables, constraints, and
indexes — **keep them in sync** when you change either.

Tables: `app_users`, `provider_profiles`, `specialties`/`provider_specialties`,
`style_tags`/`provider_style_tags`, `care_types`/`provider_care_types`,
`insurance_plans`/`provider_insurance_plans`, `patient_profiles`,
`patient_addresses`, `emergency_contacts`, `consent_forms`,
`patient_consent_acknowledgements`, `availability_slots`, `appointment_requests`,
`slot_watchers`, `provider_follows`, `notifications`, `outbox_events`.

**Integrity rules that matter:**

- `availability_slots`: status `open|booked|cancelled`; `end_at > start_at`;
  unique `(provider_id, start_at, end_at)`.
- `appointment_requests`: status `pending|confirmed|declined|cancelled|completed`;
  partial unique index preventing two live (`pending`/`confirmed`) appointments
  per slot.
- `slot_watchers`: `start_before > start_after`; partial unique index on
  `(patient_id, provider_id, start_after, start_before)` where active.
- `provider_follows`: partial unique index on `(patient_id, provider_id)` where
  active.
- `notifications`: two partial unique indexes for de-duplication —
  `(user_id, slot_id, appointment_request_id, type)` when
  `appointment_request_id IS NOT NULL`, and `(user_id, slot_id, type)` when it
  IS NULL. `provider_id`, `provider_name`, `start_at`, `end_at` are **derived
  properties** off `slot`/`slot.provider`, not columns.
- `outbox_events`: status `pending|published|failed|dead` (see §8), `payload`
  JSON snapshot, `attempt_count`, `stream_message_id`, `last_error`.

## 7. Realtime notification architecture (read this before touching it)

This is the most decision-heavy part of the system. It deliberately uses **no
external broker** and is **single-instance by design**.

### Flow: domain change → durable rows → in-process push

1. A flow that should notify (slot created, appointment cancelled/declined)
   inserts `notifications` rows **and** an `outbox_events` row **in the same DB
   transaction** (`notification_service.create_notification_outbox_event`). The
   outbox row stores a full realtime **payload snapshot**. This is the
   transactional-outbox pattern: domain state and the event commit atomically.
2. `dispatcher.dispatch_outbox_events()` — started in `main.py` `lifespan` when
   `REALTIME_DISPATCH_ENABLED=true` — polls the outbox every
   `OUTBOX_POLL_SECONDS` and calls `outbox_service.publish_pending_events`.
3. The publisher is `InProcessPublisher` (`realtime/in_process.py`), which
   implements the `OutboxPublisher` protocol and hands each payload to the
   in-memory `ConnectionManager.send_to_user`.
4. `ConnectionManager` (`realtime/manager.py`) holds `user_id -> {WebSocket}`
   in process memory and pushes the JSON frame to that user's live sockets.
5. Clients connect to `GET /ws/notifications` (see §9 for the contract).

### Why no broker, and the one hard constraint

For a **single instance**, the WebSocket sockets live in the same process as the
dispatcher, so a network broker between two threads of one process is pure
overhead. **Delivery targets in-memory sockets, therefore the dispatcher MUST
run inside the API process** — never as a separate worker (a separate process
would push into its own empty `ConnectionManager`).

### Delivery semantics (important)

Realtime delivery is **best-effort**:

- If the target user has no live socket (offline, reload, flaky network),
  `send_to_user` returns 0; the event is still marked `published`. Nothing is
  replayed over the socket later.
- Durable truth is the `notifications` table. The **reconcile contract** (§9) is
  the only thing that guarantees a user eventually sees a missed event.
- `ConnectionManager.send_to_user` prunes sockets that raise `RuntimeError`
  (already-closed) under its lock.

### Scaling later

The `OutboxPublisher` protocol is the seam. To run multiple instances, replace
`InProcessPublisher` with a broker-backed publisher and add a consumer per
gateway. For pure fan-out (every instance sees every event, delivers to local
sockets), **Redis Pub/Sub** matches these semantics with the least machinery; a
prior Redis Streams implementation was removed because, for these semantics, the
consumer-group ceremony bought nothing and shipped a replay-from-zero bug. If
reintroducing Streams, use a per-instance group keyed to a stable instance id,
read from `$`, set `MAXLEN`, and destroy the group on shutdown.

## 8. Outbox processing & dead-letter (`services/outbox_service.py`)

`publish_pending_events(db, publisher, batch_size=None, max_attempts=3)`:

- Selects events that are `pending` **or** (`failed` **and**
  `attempt_count < max_attempts`), ordered by `created_at, id`, `LIMIT batch`,
  with `FOR UPDATE SKIP LOCKED` (Postgres; see §10 caveat).
- Per event: increment `attempt_count`, call `publisher.publish(event)`.
  - Success → `published`, set `stream_message_id`, `published_at`, clear error.
  - Failure with retries left → `failed` (logged `warning`); re-tried next poll.
  - Failure at the retry ceiling → `dead` (terminal, logged `error` with
    `last_error`); never re-attempted.
- Returns `OutboxPublishResult(published, failed, dead)`.

`dead` is a real terminal state — surface it in monitoring (the `error` log is
the current signal). `published` outbox rows are retained (no trimming yet).

## 9. WebSocket endpoint contract (`/ws/notifications`)

- **Auth:** token from the `Authorization: Bearer` header (preferred — stays out
  of access logs) or the `?token=` query param (browser fallback, since browsers
  can't set WS headers). Invalid/expired → close `1008`.
- **Token expiry is enforced for the life of the connection:** the receive loop
  runs under a timeout equal to the remaining token lifetime; when the token
  expires mid-connection the socket is closed with `1008` and the client must
  reconnect with a fresh token.
- **Robustness:** malformed (non-JSON) client frames are ignored, not fatal;
  cleanup runs in `finally`, so a socket can never leak a stale registration.
- **Keepalive:** client sends `{"event": "ping"}` → server replies
  `{"event": "pong"}`.
- **Reconcile contract (clients MUST implement):** delivery is best-effort, so on
  every (re)connect the client calls `GET /notifications/me?is_read=false`,
  renders that backlog, and **dedupes live socket events by `notification_id`**
  (socket events and REST rows share the same id). This contract is documented in
  the route docstring, the `GET /notifications/me` endpoint description, the
  top-level OpenAPI description, and the README. (OpenAPI does not render
  WebSocket endpoints, so the REST endpoint + app description carry it in Swagger.)

## 10. Concurrency & race-safety

- **Booking** (`appointment_service.create_appointment_request`): locks the slot
  with `SELECT ... FOR UPDATE`, then performs an **atomic conditional update**
  (`UPDATE ... WHERE status='open' SET status='booked'`) and checks `rowcount`.
  A unique partial index plus `IntegrityError` handling guards the
  one-live-appointment-per-slot rule. Two clients cannot book the same slot.
- **Appointment status** (`update_appointment_status`, `cancel_appointment`):
  rows locked `FOR UPDATE`; transitions validated against
  `ALLOWED_STATUS_TRANSITIONS`; terminal statuses
  (`cancelled|declined|completed`) are immutable. Cancel/decline calls
  `_reopen_slot_and_notify` (slot → `open`, create `slot_reopened` notifications
  for followers/watchers except the cancelling patient).
- ⚠️ **KNOWN GAP (open):** `FOR UPDATE SKIP LOCKED` / row locks are **no-ops on
  SQLite**, which is the default and the test database. So the booking and outbox
  concurrency guarantees are real only on PostgreSQL and are **not exercised by
  the SQLite test suite**. Treat Postgres as the source of truth for concurrency
  behavior; do not infer concurrency safety from green local tests.

## 11. Notification sources: follows & watchers

`notification_service` computes recipients as **provider followers ∪ matching
slot watchers** for the slot's provider, filtered to active patient users, and
excluding a given patient where relevant (e.g. the cancelling patient on reopen):

- `ProviderFollow`: patient follows a provider → alerted on any of that
  provider's slot openings/reopenings.
- `SlotWatcher`: patient watches a `(provider, [start_after, start_before])`
  window → alerted only when the slot's `start_at` falls in the window.

Per-recipient dedup uses an existence check **and** the DB partial unique
indexes (§6). `slot_opened` notifications fire when a provider creates a slot
(`provider_service.create_my_slot`); `slot_reopened` when an appointment is
cancelled/declined.

## 12. API surface (by router)

- **auth** (`/auth`): `POST /register`, `POST /login`, `GET /me`.
- **providers** (public): `GET /providers`, `GET /providers/{id}`,
  `GET /providers/{id}/availability`, `GET /insurance-plans`.
- **provider_self** (`/providers/me`): `POST` / `GET` / `PATCH` profile;
  `POST /availability`, `GET /availability`, `DELETE /availability/{slot_id}`;
  `PUT /specialties|/insurance-plans|/style-tags|/care-types`.
  *(Registered before the public `providers` router so `/providers/me` is not
  parsed as `/providers/{id}`.)*
- **patient_self** (`/patients/me`): `GET`/`PATCH /profile`,
  `PUT /addresses`, `PUT /emergency-contacts`,
  `POST /consents/{form_key}/accept`. Addresses and emergency contacts are
  **full-list replacements** (`PUT`); profile is a singleton, `PATCH` is partial
  and creates it when missing.
- **appointments** (`/appointment-requests`): `POST`, `GET /me`,
  `GET /provider`, `PATCH /{id}/status`, `POST /{id}/cancel`.
- **follows** (`/provider-follows`): `POST`, `GET /me`, `DELETE /{id}`.
- **watchers** (`/slot-watchers`): `POST`, `GET /me`, `DELETE /{id}`.
- **notifications** (`/notifications`): `GET /me` (reconcile source),
  `PATCH /{id}/read`.
- **realtime**: `WebSocket /ws/notifications`.
- **system**: `GET /health`.

## 13. Running

```bash
uv sync
uv run python -m scripts.seed                       # demo data
uv run uvicorn app.main:app --reload                # API (no realtime)
REALTIME_DISPATCH_ENABLED=true uv run uvicorn app.main:app --reload  # with realtime
```

Demo accounts (password `Password123!`): `patient@example.com`,
`patient2@example.com`, `provider@example.com`, `admin@example.com`.

**Docker:** `docker compose up --build` (services: `api` with
`REALTIME_DISPATCH_ENABLED=true`, and `db` Postgres — no Redis, no worker).

**Supabase / Postgres:** see `SUPABASE_SETUP.md`. Use
`postgresql+psycopg://...`, run `supabase/schema.sql` once, set `ENVIRONMENT=production`
and a strong `JWT_SECRET_KEY`.

## 14. Testing

```bash
uv run pytest
```

SQLite-backed, file-per-test via the `session_factory`/`client` fixtures in
`tests/conftest.py` (which also seeds `seeded_data`). Realtime delivery is tested
by unit-testing `InProcessPublisher` against a fake `ConnectionManager`/socket
and by driving `publish_pending_events` directly (TestClient WebSockets run in a
separate event loop, so end-to-end socket delivery is not asserted through the
TestClient). Remember §10: concurrency paths are not meaningfully tested on
SQLite.

## 15. Conventions for agents

- Keep routers thin; put logic and queries in `services/`.
- Raise `HTTPException` for client errors; use precise status codes.
- When you change a table, update **both** `app/models.py` and
  `supabase/schema.sql`, and adjust `tests/` + seed data.
- Datetimes are timezone-aware UTC; persist with `DateTime(timezone=True)`.
- Don't reintroduce a message broker for realtime unless you are actually
  running multiple instances; if you do, go through the `OutboxPublisher` seam
  and read §7's scaling notes first.
- Treat the WebSocket reconcile contract (§9) as load-bearing — changing
  delivery semantics without it silently loses notifications.

## 16. Open items / backlog

- **Concurrency tests on Postgres** (§10): row-lock guarantees are unverified by
  the SQLite suite. Add a Postgres-backed concurrency test, or fail loudly when
  the engine lacks row-lock support.
- **Outbox stream/table growth:** `published` outbox rows are never pruned; add a
  retention/cleanup job.
- **Dead-letter alerting:** `dead` events only emit an `error` log today; wire a
  metric/alert if outbox failures need operational visibility.
- **Horizontal scaling:** realtime is single-instance by design (§7).
