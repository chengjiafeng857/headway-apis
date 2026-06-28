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
- SQLAlchemy models compatible with PostgreSQL/Supabase

## Local Run

```bash
uv sync
uv run python -m scripts.seed
uv run uvicorn app.main:app --reload
```

For Docker:

```bash
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
