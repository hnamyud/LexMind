# Core API

Primary FastAPI backend. It uses the shared repository-root `.env`, while keeping an independent `.venv` and Docker image from `ai-service`.

## Local development

Install [uv](https://docs.astral.sh/uv/) and run from this directory:

```powershell
uv sync --all-groups
uv run uvicorn app.main:app --reload --port 8080
uv run arq app.workers.mail.WorkerSettings
```

The service exposes both legacy routes such as `/auth/login` and versioned aliases such as `/api/v1/auth/login`. Docker Compose maps it to port `8080`.

## Database migrations

Alembic owns migrations for the Core API tables. Existing production databases must first be stamped at `20260727_prisma_baseline`, then upgraded to head. Do not downgrade below the baseline in production.
