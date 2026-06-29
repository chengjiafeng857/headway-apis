# Supabase Setup

Use Supabase as hosted PostgreSQL. FastAPI remains the public API layer and uses SQLAlchemy for all reads and writes.

## Steps

1. Create a Supabase project.
2. In Supabase project settings, copy the Postgres connection string.
3. Copy the example env file and fill in secrets locally:

   ```bash
   cp .env.example .env
   ```

4. Use the SQLAlchemy psycopg format:

   ```text
   DATABASE_URL=postgresql+psycopg://postgres:<rotated-password>@<host>:5432/postgres?sslmode=require
   ```

   If EC2 has IPv4-only networking, use Supabase's session pooler connection string instead.

5. Set app secrets in `.env` or the deployment environment:

   ```text
   DATABASE_URL=postgresql+psycopg://...
   JWT_SECRET_KEY=<long-random-secret>
   JWT_EXPIRE_MINUTES=60
   AUTO_CREATE_TABLES=false
   ENVIRONMENT=production
   REALTIME_DISPATCH_ENABLED=true
   ```

   `REALTIME_DISPATCH_ENABLED=true` runs the in-process outbox dispatcher that
   pushes notifications to connected WebSocket sockets. This is single-instance
   only — delivery is in-memory, so it must run inside the API process. To scale
   horizontally later, reintroduce a broker between the outbox and the gateways.

6. Initialize the schema once by running `supabase/schema.sql` in the Supabase SQL Editor or
   through `psql`.

7. Start the API container, then seed demo data once if needed:

   ```bash
   python -m scripts.seed
   ```

If you want to create the schema directly from the Supabase SQL editor instead, run
`supabase/schema.sql`. The app models and the SQL file define the same tables,
constraints, and indexes.

## Security Notes

- This project uses manual JWT auth in FastAPI, not Supabase Auth.
- Do not expose the Supabase anon key to this API unless direct client access is later added.
- Rotate any database password that has been pasted into chat or committed by mistake.
- Keep all database writes behind FastAPI role checks.
- The schema uses constraints and partial unique indexes to protect appointment integrity.
- The booking endpoint uses a row lock plus an atomic conditional update so two clients cannot book the same open slot.
- Realtime WebSocket delivery uses the existing FastAPI JWT; do not expose Supabase service credentials to the frontend.
- Keep `notifications` as durable truth and WebSockets as delivery acceleration.
