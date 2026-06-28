# Supabase Setup

Use Supabase as hosted PostgreSQL. FastAPI remains the public API layer and uses SQLAlchemy for all reads and writes.

## Steps

1. Create a Supabase project.
2. In Supabase project settings, copy the Postgres connection string.
3. Use the SQLAlchemy psycopg format:

   ```text
   DATABASE_URL=postgresql+psycopg://postgres:<password>@<host>:5432/postgres
   ```

   If EC2 has IPv4-only networking, use Supabase's session pooler connection string instead.

4. Set app secrets on EC2:

   ```text
   DATABASE_URL=postgresql+psycopg://...
   JWT_SECRET_KEY=<long-random-secret>
   AUTO_CREATE_TABLES=true
   ENVIRONMENT=production
   ```

5. Start the API container, then seed demo data once:

   ```bash
   python -m scripts.seed
   ```

If you want to create the schema directly from the Supabase SQL editor instead, run
`supabase/schema.sql`. The app models and the SQL file define the same tables,
constraints, and indexes.

## Security Notes

- This project uses manual JWT auth in FastAPI, not Supabase Auth.
- Do not expose the Supabase anon key to this API unless direct client access is later added.
- Keep all database writes behind FastAPI role checks.
- The schema uses constraints and partial unique indexes to protect appointment integrity.
- The booking endpoint uses a row lock plus an atomic conditional update so two clients cannot book the same open slot.
