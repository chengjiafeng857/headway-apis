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
   REDIS_URL=redis://<host>:6379/0
   REDIS_NOTIFICATIONS_STREAM=notifications:stream
   WEBSOCKET_REDIS_CONSUMER_ENABLED=true
   ```

   Leave `REDIS_CONSUMER_GROUP` unset unless you intentionally manage routing.
   The default is unique per FastAPI process so every WebSocket gateway instance
   can observe each event and deliver only to locally connected sockets.

6. Initialize the schema once by running `supabase/schema.sql` in the Supabase SQL Editor or
   through `psql`.

7. Start the API container, then seed demo data once if needed:

   ```bash
   python -m scripts.seed
   ```

8. Run the outbox worker as a separate process or container:

   ```bash
   python -m scripts.outbox_worker
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
- Keep `notifications` as durable truth and Redis/WebSockets as delivery acceleration.
