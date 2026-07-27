# Chatbot Law

Hệ thống chatbot tư vấn luật giao thông gồm hai dịch vụ FastAPI:

| Service | Vai trò | Port |
| --- | --- | --- |
| `core-api` | Auth, chat, conversation, admin, mail queue | `8080` |
| `ai-service` | RAG, Neo4j retrieval và LLM streaming | `8001` |

Redis phục vụ cache và ARQ mail worker. PostgreSQL lưu dữ liệu nghiệp vụ; Neo4j lưu knowledge graph.

## Chạy local

1. Tạo `.env` từ `.env.example` và điền secrets cần thiết.
2. Tạo môi trường Python cho hai service:

   ```powershell
   cd ai-service; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
   cd ..\core-api; uv sync --all-groups
   ```

3. Khởi động Redis, sau đó chạy:

   ```powershell
   .\dev.ps1
   ```

Core API chạy tại `http://localhost:8080`; AI API tại `http://localhost:8001`.

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

Compose chạy một `core-migrate` one-shot trước Core API và mail worker. Lần chuyển đổi đầu tiên từ database Prisma cần stamp baseline trước khi `up`:

```powershell
docker compose run --rm core-migrate python -m alembic stamp 20260727_prisma_baseline
docker compose up -d --build --remove-orphans
```

Sau đó `core-migrate` tự chạy `alembic upgrade head` cho mỗi image/deploy mới.

## Database migrations

`core-api/alembic` là nguồn migration duy nhất của các bảng `users`, `conversations`, `messages`, `feedbacks` và `ai_metrics`. Không chạy downgrade thấp hơn revision baseline trên database production.

Các bảng checkpoint của AI service và bảng `_prisma_migrations` lịch sử không thuộc Alembic.

## API

Core API hỗ trợ cả route hiện hữu, ví dụ `/auth/login`, và alias versioned `/api/v1/auth/login`. Health check: `GET /healthz`.

Tài liệu API được lưu trong `core-api/docs`.
