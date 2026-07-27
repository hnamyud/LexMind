# LexMind — Chatbot Tư Vấn Luật Giao Thông Việt Nam

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.140+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Neo4j](https://img.shields.io/badge/Neo4j-Knowledge%20Graph-4581C3.svg)](https://neo4j.com/)
[![Redis](https://img.shields.io/badge/Redis-Cache%20%26%20Queue-DC382D.svg)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)

**LexMind** là chatbot hỗ trợ tra cứu và tư vấn luật giao thông Việt Nam. Hệ thống kết hợp RAG, Knowledge Graph Neo4j và web search để trả lời có căn cứ, ưu tiên trích dẫn nguồn pháp lý thay vì suy đoán.

Nội dung trọng tâm gồm **Nghị định 168/2024/NĐ-CP**, **Luật Đường bộ 2024** và các nguồn pháp luật được nạp vào knowledge graph.

---

## Mục lục

- [Tính năng](#tính-năng)
- [Kiến trúc](#kiến-trúc)
- [Tech stack](#tech-stack)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Dữ liệu & migrations](#dữ-liệu--migrations)
- [API](#api)
- [Chạy local](#chạy-local)
- [Chạy Docker Compose](#chạy-docker-compose)
- [Biến môi trường](#biến-môi-trường)
- [Tài liệu](#tài-liệu)

---

## Tính năng

- **Hybrid legal RAG** — kết hợp Neo4j Knowledge Graph, semantic retrieval và web search khi cần.
- **Streaming chat** — Core API proxy luồng SSE từ AI service về client theo thời gian thực.
- **Câu trả lời có căn cứ** — pipeline ưu tiên điều, khoản và nguồn luật phù hợp; reflector kiểm tra vùng mơ hồ trước khi trả lời.
- **Authentication** — đăng nhập local, JWT access/refresh token, Google OAuth và luồng đặt lại mật khẩu qua OTP.
- **Quản lý hội thoại** — tạo, đổi tên, soft delete, lịch sử tin nhắn và cursor pagination cho danh sách dài.
- **Feedback loop** — người dùng có thể like/dislike phản hồi; số liệu AI và feedback phục vụ dashboard/admin.
- **Background worker** — ARQ + Redis xử lý email không chặn request chính.
- **Operational readiness** — health check kiểm tra PostgreSQL, Redis và AI service; Docker Compose chạy migration trước API.

---

## Kiến trúc

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend client                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP / SSE
                ┌──────────────┴──────────────┐
                ▼                             ▼
┌────────────────────────────────┐  ┌─────────────────────────────┐
│ Core API — FastAPI             │  │ AI Service — FastAPI        │
│ :8080                          │  │ :8001                       │
│                                │  │                             │
│ • JWT / Google OAuth / OTP     │  │ • LangGraph agent           │
│ • Chat stream proxy            │──│ • Legal RAG & reflection    │
│ • Conversations & feedback     │  │ • Neo4j graph retrieval     │
│ • Admin / evaluation API       │  │ • Model & web-search tools  │
│ • Mail queue producer          │  │ • Checkpoint persistence    │
└───────────────┬────────────────┘  └──────────────┬──────────────┘
                │                                   │
       ┌────────┴────────┐                 ┌────────┴─────────┐
       ▼                 ▼                 ▼                  ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ PostgreSQL  │   │ Redis + ARQ │   │ Neo4j graph │   │ LLM provider│
│ users/chat  │   │ cache/mail  │   │ legal data  │   │ OpenAI/Gemini│
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
```

| Service | Port | Trách nhiệm |
| --- | ---: | --- |
| `core-api` | `8080` | API nghiệp vụ, auth, chat, conversation, admin, mail queue |
| `ai-service` | `8001` | RAG, legal graph retrieval, LLM orchestration, streaming |
| `core-mail-worker` | — | Consumer ARQ cho email background |
| `redis` | `6380` host / `6379` container | Cache, queue và worker coordination |

---

## Tech stack

| Thành phần | Công nghệ |
| --- | --- |
| API backend | FastAPI, Uvicorn, Pydantic Settings |
| ORM & migration | SQLAlchemy async, Alembic, asyncpg, psycopg |
| Authentication | JWT, bcrypt, Authlib Google OAuth, Starlette sessions |
| Queue & cache | Redis, ARQ |
| AI orchestration | LangGraph, LangChain, LLM providers |
| Knowledge graph | Neo4j |
| Retrieval | ONNX Runtime + `huyydangg/DEk21_hcmute_embedding` |
| Observability | Health checks, request ID, response-time headers |
| Deployment | Docker, Docker Compose |

---

## Cấu trúc thư mục

```text
Chatbot-law/
├── core-api/                         # FastAPI nghiệp vụ chính
│   ├── app/
│   │   ├── api/                      # Auth, chat, resources, admin, mail
│   │   ├── core/                     # Config, security, response contract
│   │   ├── db/                       # SQLAlchemy models và session
│   │   └── workers/                  # ARQ mail worker
│   ├── alembic/                      # Schema migrations
│   ├── docs/                         # API reference
│   └── tests/
├── ai-service/                       # FastAPI RAG service
│   ├── app/
│   │   ├── graph/                    # LangGraph builder và streaming
│   │   ├── nodes/                    # Router, retriever, reflector, synthesis
│   │   ├── services/                 # RAG và embedding services
│   │   ├── tools/                    # Neo4j/vector/web retrieval
│   │   └── prompts/                  # Prompt YAML
│   └── main.py
├── docker-compose.yml                # Local/production-like stack
├── dev.ps1                           # Windows dev launcher
└── .env.example                      # Environment template
```

---

## Dữ liệu & migrations

Core API quản lý các bảng nghiệp vụ bằng Alembic:

```text
User ──< Conversation ──< Message ──< AI Metrics
  │                            │
  └────────────< Feedback >────┘
```

- `users` — tài khoản, role và refresh token.
- `conversations`, `messages` — lịch sử chat; hỗ trợ keyset/cursor pagination.
- `feedbacks` — đánh giá phản hồi của người dùng.
- `ai_metrics` — thời gian, token, tool call, cache hit và lỗi AI.

Alembic không quản lý các bảng LangGraph checkpoint của AI service. `_prisma_migrations` được giữ lại chỉ để làm lịch sử migration trước cutover.

### Lần deploy đầu tiên từ database cũ

Database đã tồn tại cần được stamp baseline trước; không chạy `upgrade` trực tiếp vì baseline mô tả schema hiện hữu.

```powershell
docker compose run --rm core-migrate python -m alembic stamp 20260727_prisma_baseline
docker compose up -d --build --remove-orphans
```

Sau đó `core-migrate` chạy `alembic upgrade head` trước Core API và mail worker mỗi khi image được triển khai.

> Không chạy downgrade thấp hơn `20260727_prisma_baseline` trên production.

---

## API

Core API giữ route hiện hữu và có alias `/api/v1` tương ứng.

| Nhóm | Ví dụ endpoint |
| --- | --- |
| Health | `GET /healthz` |
| Auth | `POST /auth/login`, `GET /auth/refresh`, `GET /auth/google/login` |
| Chat | `POST /chat/ask/stream` và stream response |
| Conversations | `GET /conversations`, `GET /conversations/cursor` |
| Messages | `GET /messages/conversation/:id`, cursor history |
| Feedback | `POST /feedbacks/message/:message_id` |
| Admin | `/admin/*` |

Khi stack chạy local:

- Swagger UI: [http://localhost:8080/docs](http://localhost:8080/docs)
- OpenAPI JSON: [http://localhost:8080/openapi.json](http://localhost:8080/openapi.json)
- Core health: [http://localhost:8080/healthz](http://localhost:8080/healthz)
- AI health: [http://localhost:8001/health](http://localhost:8001/health)

---

## Chạy local

### Yêu cầu

- Python `3.11+`
- [uv](https://docs.astral.sh/uv/) cho `core-api`
- Docker Desktop hoặc Redis local
- PostgreSQL, Neo4j và LLM credentials được cấu hình trong `.env`

### Cài đặt

```powershell
Copy-Item .env.example .env

cd ai-service
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

cd ..\core-api
uv sync --all-groups
```

Khởi động Redis, sau đó chạy từ root:

```powershell
.\dev.ps1
```

Script mở ba process riêng: AI API (`8001`), Core API (`8080`) và mail worker.

---

## Chạy Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

Kiểm tra stack:

```powershell
Invoke-WebRequest http://localhost:8080/healthz
Invoke-WebRequest http://localhost:8001/health
docker compose logs -f core-api
```

Dừng stack nhưng giữ data volumes:

```powershell
docker compose down
```

---

## Biến môi trường

| Biến | Mô tả |
| --- | --- |
| `APP_ENV` | `development` hoặc `production`; ảnh hưởng secure cookie/OAuth session |
| `DATABASE_URL` | PostgreSQL URL cho Core API |
| `REDIS_URL` | Redis URL cho cache và ARQ |
| `AI_SERVICE_URL` | URL nội bộ của AI service, ví dụ `http://ai-service:8001` |
| `FE_DOMAIN` | Origin frontend được phép CORS |
| `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET` | Secrets ký access/refresh token |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth, nếu bật |
| `SESSION_SECRET` | Secret ký OAuth session cookie |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Kết nối knowledge graph |
| `LOCAL_API_KEY`, `BASE_URL` | OpenAI-compatible LLM provider |
| `GOOGLE_API_KEY` | Google provider, nếu dùng |

`NODE_ENV`, `PORT`, `LEXMIND_AI_SERVICE_URL` và `FASTAPI_URL` vẫn được Core API nhận như alias tương thích trong một chu kỳ migration; cấu hình mới nên dùng `APP_ENV`, `CORE_API_PORT` và `AI_SERVICE_URL`.

---

## Tài liệu

- [Core API README](core-api/README.md)
- [Core API endpoint reference](core-api/docs/index.md)
- [Cursor pagination](core-api/docs/frontend-cursor-pagination.md)

## License

Distributed under the [MIT License](LICENSE).
