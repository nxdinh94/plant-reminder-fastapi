# FastAPI Backend

Backend service for Plant Reminder at:

- `D:\Code\JETPACK_COMPOSE\graduation_project\fastapi_backend`

## Requirements

- Python 3.11+
- PostgreSQL 15+

## Local Run

1. Create and activate virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Copy env file:

```bash
cp .env.example .env
```

PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

4. Start PostgreSQL in Docker:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

5. Run database migrations:

```bash
alembic upgrade head
```

6. Start API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## PostgreSQL in Docker

Run PostgreSQL only (for local FastAPI running on your host):

```bash
docker compose -f docker-compose.postgres.yml up -d
```

Stop it:

```bash
docker compose -f docker-compose.postgres.yml down
```

Auto-start behavior:
- Database container is configured with `restart: always`.
- After first successful `up -d`, it starts automatically when Docker Desktop starts.

With this mode, keep `DATABASE_URL` in `.env` as:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/plant_reminder
```

## Full Docker Compose (DB + API)

```bash
docker compose up --build
```

In full compose mode, API uses container-to-container DB URL (`db:5432`) automatically.

## Endpoints

- Health:
  - `GET /api/v1/health/live`
  - `GET /api/v1/health/ready`
- Auth:
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/refresh`
  - `GET /api/v1/auth/session`
- Sync:
  - `GET /api/v1/sync/capabilities`
  - `GET /api/v1/sync/bootstrap`
  - `POST /api/v1/sync/push`
  - `GET /api/v1/sync/pull?since=...`
- Feature APIs:
  - `GET/POST/PATCH/DELETE /api/v1/plants`
  - `GET/POST/PATCH/DELETE /api/v1/action-types`
  - `GET/POST/PATCH/DELETE /api/v1/schedules`
  - `GET/POST/PATCH/DELETE /api/v1/task-completions`
  - `PUT /api/v1/task-completions/{schedule_id}/{completion_date}/toggle`
  - `GET/POST/PATCH/DELETE /api/v1/notes`
  - `GET/POST/PATCH/DELETE /api/v1/timelines`
  - `GET/PUT /api/v1/profile/settings`
