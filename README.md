# Chatbot Luật Giao Thông Việt Nam 🇻🇳

Hệ thống chatbot hỗ trợ tra cứu và tư vấn luật giao thông Việt Nam (Nghị định 168/2024/NĐ-CP), sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp **Knowledge Graph** và **Web Search** để cung cấp câu trả lời chính xác, có trích dẫn nguồn.

## Mục lục

- [Kiến trúc hệ thống](#kiến-trúc-hệ-thống)
- [Tech Stack](#tech-stack)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Database Schema](#database-schema)
- [AI Service — RAG Pipeline](#ai-service--rag-pipeline)
- [Backend Core — NestJS API](#backend-core--nestjs-api)
- [API Endpoints](#api-endpoints)
- [Luồng hoạt động](#luồng-hoạt-động)
- [Biến môi trường](#biến-môi-trường)
- [Hướng dẫn cài đặt & chạy](#hướng-dẫn-cài-đặt--chạy)

---

## Kiến trúc hệ thống

```
┌──────────────────────────────────────────────────────────────┐
│                       Frontend Client                        │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTP / SSE
              ┌──────────────┴───────────────┐
              ▼                              ▼
┌───────────────────────────────┐  ┌──────────────────────────────┐
│     NestJS Backend-Core       │  │     FastAPI AI-Service        │
│     (Port 8080, /api/v1)      │  │     (Port 8001)              │
│                               │  │                              │
│  • Auth (JWT + Google OAuth)  │  │  • LangGraph Agent (ReAct)   │
│  • Conversation management    │──│  • Neo4j Knowledge Graph     │
│  • Messages & Feedbacks       │  │  • Web Search (Serper)       │
│  • User management            │  │  • Firecrawl Web Scraping    │
│  • RBAC (CASL)                │  │  • PostgreSQL Checkpointer   │
│  • Rate Limiting              │  │  • Gemini 2.5 Flash LLM      │
└───────────────┬───────────────┘  └──────────────┬───────────────┘
                │                                  │
       ┌────────┴────────┐                ┌────────┴────────┐
       ▼                 ▼                ▼                 ▼
 ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
 │PostgreSQL │    │   Redis   │    │   Neo4j   │    │PostgreSQL │
 │ (Prisma)  │    │  (Cache)  │    │ (Knowledge│    │(LangGraph │
 │           │    │           │    │   Graph)  │    │Checkpoint)│
 └───────────┘    └───────────┘    └───────────┘    └───────────┘
```

**Monorepo** gồm 2 service chính:

| Service | Ngôn ngữ | Framework | Port | Chức năng |
|---------|-----------|-----------|------|-----------|
| **backend-core** | TypeScript | NestJS 11 | 8080 | API gateway, auth, quản lý hội thoại |
| **ai-service** | Python | FastAPI | 8001 | RAG pipeline, LLM reasoning, tìm kiếm |

---

## Tech Stack

| Thành phần | Công nghệ | Phiên bản |
|------------|-----------|-----------|
| Backend Framework | NestJS | 11.0.1 |
| ORM | Prisma | 7.4.2 |
| Authentication | Passport (JWT, Local, Google OAuth) | 0.7.0 |
| Authorization | CASL | 6.7.3 |
| API Docs | Swagger / OpenAPI | 11.0.0 |
| Cache & Queue | Redis (ioredis) + Bull | 5.10.0 / 4.16.5 |
| AI Framework | FastAPI | 0.115.9 |
| LLM Orchestration | LangGraph | 1.0.9 |
| LLM Model | Google Gemini 2.5 Flash | Latest |
| Knowledge Graph | Neo4j | 5.28.1 |
| Embeddings | SentenceTransformers (vietnamese-sbert) | 4.1.0 |
| Web Search | Serper.dev + Firecrawl | Via SDK |
| State Management | LangGraph AsyncPostgresSaver | 4.0.0 |
| Security | Helmet, bcryptjs | 8.1.0 / 2.4.3 |
| Testing | Jest (Backend) + pytest (AI) | 30.2.0 / 9.0.2 |

---

## Cấu trúc thư mục

```
Chatbot-law/
├── dev.ps1                     # Script khởi chạy cả 2 service (Windows)
├── package.json                # Root monorepo (concurrently)
│
├── backend-core/               # NestJS API Server
│   ├── prisma/
│   │   ├── schema.prisma       # Database schema
│   │   └── migrations/         # Migration history
│   └── src/
│       ├── main.ts             # Entry point (port 8080)
│       ├── app.module.ts       # Root module
│       ├── common/             # Enums, Guards, Interfaces
│       ├── config/             # Helmet, Google OAuth config
│       ├── core/               # CASL, Decorators, Interceptors, Middleware
│       ├── modules/
│       │   ├── auth/           # JWT + Google OAuth + OTP
│       │   ├── chat/           # Stream proxy đến AI service
│       │   ├── conversations/  # CRUD hội thoại
│       │   ├── messages/       # Lịch sử tin nhắn
│       │   ├── feedbacks/      # Like/dislike câu trả lời
│       │   └── users/          # Quản lý người dùng
│       └── shared/
│           ├── cache/          # Redis cache module
│           └── mailer/         # Email service
│
└── ai-service/                 # FastAPI AI Server
    ├── main.py                 # Entry point (port 8001)
    └── app/
        ├── api/routes.py       # API endpoints
        ├── core/
        │   ├── config.py       # Environment config
        │   ├── state.py        # LangGraph state schema
        │   └── checkpoint.py   # PostgreSQL checkpointer
        ├── services/
        │   └── rag_service.py  # RAG pipeline & LangGraph graph
        ├── prompts/            # System prompts (YAML)
        │   ├── synthesis.yaml
        │   ├── router_rewrite.yaml
        │   └── rewrite_legal_query.yaml
        └── tools/
            ├── graph_retrieval.py  # Neo4j vector search
            └── web_search.py       # Serper + Firecrawl
```

---

## Database Schema

### PostgreSQL (Prisma)

```
┌──────────┐     1:N     ┌──────────────┐     1:N     ┌──────────┐
│   User   │────────────▶│ Conversation │────────────▶│ Message  │
│          │             │              │             │          │
│ id (UUID)│             │ id (UUID)    │             │ id (UUID)│
│ email    │             │ userId (FK)  │             │ parentId │
│ password │             │ title        │             │ convId   │
│ fullName │             │ summary      │             │ sender   │
│ role     │             │ isDeleted    │             │ content  │
│          │             │ deletedAt    │             │ metadata │
└──────┬───┘             └──────────────┘             └────┬─────┘
       │                                                    │
       │         1:N     ┌──────────┐     N:1              │
       └────────────────▶│ Feedback │◀─────────────────────┘
                         │          │
                         │ id (UUID)│
                         │ messageId│
                         │ userId   │
                         │ isLike   │
                         │ reason   │
                         └──────────┘
```

| Model | Mô tả |
|-------|--------|
| **User** | Tài khoản người dùng. Role: `ADMIN` / `USER`. Hỗ trợ soft-delete. |
| **Conversation** | Phiên hội thoại. Soft-delete (`isDeleted`). Liên kết với User. |
| **Message** | Tin nhắn trong hội thoại. `sender`: `user` / `bot`. `parentId` tạo cặp Q&A. `metadata` lưu sources JSON. |
| **Feedback** | Đánh giá câu trả lời. Unique constraint: 1 user / 1 message. |

Ngoài ra, LangGraph sử dụng 4 bảng riêng cho **checkpoint** (quản lý bộ nhớ hội thoại stateful):
`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`.

---

## AI Service — RAG Pipeline

### Kiến trúc LangGraph

```
                    ┌─────────┐
                    │  START  │
                    └────┬────┘
                         ▼
                  ┌──────────────┐
           ┌─────│    Agent     │◀────────────┐
           │     │ (Gemini LLM) │             │
           │     └──────┬───────┘             │
           │            │                     │
     (final answer)  (tool call)        (tool result)
           │            ▼                     │
           │     ┌──────────────┐             │
           │     │    Tools     │─────────────┘
           │     │              │
           │     │ • graph_search (Neo4j)
           │     │ • web_search (Serper)
           │     └──────────────┘
           ▼
    ┌──────────────┐
    │   Fallback   │ ← Kích hoạt khi phát hiện thiếu thông tin
    │  Web Search  │
    └──────┬───────┘
           ▼
       ┌────────┐
       │  END   │
       └────────┘
```

### Các thành phần chính

| Component | Mô tả |
|-----------|--------|
| **Agent Node** | Gemini 2.5 Flash với `include_thoughts=True`. Sử dụng ReAct pattern: suy luận → chọn tool → tổng hợp. |
| **Knowledge Graph Search** | Vector search trên Neo4j (top-5 kết quả) + 2-hop graph traversal để tìm điều luật liên quan. Embedding: `keepitreal/vietnamese-sbert`. |
| **Web Search** | Tìm kiếm 2 tầng: **Tier 1** (nguồn chính phủ: vanban.chinhphu.vn, moj.gov.vn) → **Tier 2** (nguồn đáng tin: thuvienphapluat.vn). Sử dụng Serper.dev + Firecrawl. |
| **Fallback Search** | Tự động kích hoạt khi câu trả lời chứa cụm "không có thông tin" hoặc "không tìm thấy". |
| **Checkpointer** | `AsyncPostgresSaver` lưu trạng thái hội thoại theo `thread_id` (= `conversation_id`), hỗ trợ multi-turn chat. |
| **Prompts** | YAML templates: synthesis (tổng hợp câu trả lời), router_rewrite (phân loại & viết lại query), rewrite_legal_query (chuẩn hóa thuật ngữ pháp lý). |

### Response Format (NDJSON Streaming)

```jsonl
{"type": "thinking", "content": "Phân tích câu hỏi..."}
{"type": "thought", "content": "Đang tìm kiếm trong knowledge graph..."}
{"type": "answer", "content": "Theo Nghị định 168/2024..."}
{"type": "metadata", "content": {"sources": [...]}}
{"type": "done"}
```

---

## Backend Core — NestJS API

### Xác thực (Authentication)

- **Local Strategy**: Đăng nhập bằng email/password
- **JWT Strategy**: Access Token (Bearer) + Refresh Token (httpOnly cookie)
- **Google OAuth**: Đăng nhập/đăng ký qua Google
- **OTP**: Xác minh email để reset mật khẩu

### Phân quyền (CASL RBAC)

| Role | Quyền hạn |
|------|-----------|
| **ADMIN** | Toàn quyền trên mọi resource |
| **USER** | CRUD conversation của mình, tạo feedback, xem/sửa profile |

### Guards

| Guard | Chức năng |
|-------|-----------|
| `JwtAuthGuard` | Global — xác thực JWT. Bỏ qua với `@Public()` |
| `PoliciesGuard` | Global — kiểm tra quyền CASL với `@CheckPolicies()` |
| `ConversationOwnerGuard` | Xác minh user sở hữu conversation |
| `AppThrottlerGuard` | Rate limiting đa tầng: 10req/60s, 100req/30m, 200req/1h |

### Response chuẩn hóa

```json
{
  "statusCode": 200,
  "message": "Thành công!",
  "data": { ... }
}
```

---

## API Endpoints

### Authentication — `/api/v1/auth`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| POST | `/register` | Đăng ký tài khoản | Public |
| POST | `/login` | Đăng nhập (email + password) | Local |
| POST | `/logout` | Đăng xuất | JWT |
| GET | `/google/login` | Đăng nhập Google OAuth | Google |
| GET | `/google/callback` | Callback Google OAuth | Google |
| GET | `/profile` | Lấy thông tin user | JWT |
| POST | `/verify-otp` | Xác minh OTP | Public |
| POST | `/reset-password` | Đặt lại mật khẩu | Public |
| POST | `/change-password` | Đổi mật khẩu | JWT |

### Chat — `/api/v1/chat`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| POST | `/ask/stream` | Gửi câu hỏi, nhận stream câu trả lời | JWT + Throttle + Owner |
| POST | `/regenerate/:messageId` | Tạo lại câu trả lời bị lỗi | JWT + Throttle |

### Conversations — `/api/v1/conversations`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| GET | `/` | Danh sách hội thoại (phân trang) | JWT + CASL |
| PUT | `/:id` | Cập nhật tiêu đề / tóm tắt | JWT + CASL |
| DELETE | `/:id` | Xóa mềm hội thoại | JWT + CASL |

### Messages — `/api/v1/messages`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| GET | `/` | Lịch sử tin nhắn (phân trang theo conversationId) | JWT |

### Feedbacks — `/api/v1/feedbacks`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| POST | `/message/:messageId` | Gửi đánh giá (like/dislike + lý do) | JWT |
| GET | `/message/:messageId` | Xem đánh giá (Admin only) | JWT + CASL Admin |

### AI Service (Internal) — `http://127.0.0.1:8001`

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| GET | `/` | Health check |
| GET | `/health` | Trạng thái kết nối (Neo4j, Gemini, Embedding) |
| GET | `/debug` | Thông tin debug hệ thống |
| POST | `/ask/stream` | RAG pipeline (body: `{question, conversation_id}`) |
| DELETE | `/conversations/{id}/checkpoints` | Xóa bộ nhớ LangGraph của hội thoại |

---

## Luồng hoạt động

### Hỏi đáp (ask/stream)

```
Client                    NestJS (:8080)                FastAPI (:8001)
  │                            │                              │
  │ POST /chat/ask/stream      │                              │
  │ {question, conversationId} │                              │
  │───────────────────────────▶│                              │
  │                            │ 1. Validate JWT              │
  │                            │ 2. Check conversation owner  │
  │                            │ 3. Create/update conversation│
  │                            │ 4. Save user message         │
  │                            │                              │
  │                            │ POST /ask/stream             │
  │                            │ {question, conversation_id}  │
  │                            │─────────────────────────────▶│
  │                            │                              │ 5. Load checkpoint
  │                            │                              │ 6. Agent reasoning
  │                            │                              │ 7. Tool calls:
  │                            │                              │    - Neo4j search
  │                            │                              │    - Web search
  │                            │                              │ 8. Synthesize answer
  │                            │    NDJSON stream              │
  │     SSE stream             │◀─────────────────────────────│
  │◀───────────────────────────│                              │
  │                            │ 9. Save bot message + metadata│
  │                            │                              │
```

### Tái tạo câu trả lời (regenerate)

```
1. POST /chat/regenerate/:messageId
2. Xóa tin nhắn bot bị lỗi khỏi DB
3. DELETE /conversations/{id}/checkpoints → xóa bộ nhớ LangGraph
4. Lấy lại câu hỏi gốc từ parentId
5. Gửi lại request đến AI service → stream câu trả lời mới
```

### Luồng xác thực

```
Đăng nhập:
  POST /auth/login {email, password}
    → Validate credentials (LocalStrategy)
    → Tạo Access Token (JWT, short-lived)
    → Tạo Refresh Token (httpOnly cookie, long-lived)
    → Response: {access_token, user}

Refresh Token:
  → Access Token hết hạn
  → Gửi Refresh Token từ cookie
  → Cấp Access Token mới + Refresh Token mới
  → Xoay vòng Refresh Token (rotation)

Google OAuth:
  GET /auth/google/login → Redirect Google consent
  GET /auth/google/callback → Tạo/tìm user → JWT + redirect FE
```

---

## Biến môi trường

### AI Service (`ai-service/.env`)

```bash
# PostgreSQL (LangGraph Checkpoint)
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/chatbot_law

# Neo4j Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# Google Gemini LLM
GOOGLE_API_KEY=your_gemini_api_key

# Embedding Model
EMBED_MODEL_ID=keepitreal/vietnamese-sbert

# Web Search
SERPER_API_KEY=your_serper_api_key
FIRECRAWL_API_KEY=your_firecrawl_api_key
```

### Backend Core (`backend-core/.env`)

```bash
# PostgreSQL (Prisma)
DATABASE_URL=postgresql://user:password@localhost:5432/chatbot_law

# JWT
JWT_ACCESS_SECRET=your_access_secret
JWT_ACCESS_EXPIRED=15m
JWT_REFRESH_SECRET=your_refresh_secret
JWT_REFRESH_EXPIRED=30d

# Google OAuth
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback

# Frontend CORS
FE_DOMAIN=http://localhost:3000

# Server
PORT=8080
```

---

## Hướng dẫn cài đặt & chạy

### Yêu cầu

- **Node.js** >= 18
- **Python** >= 3.10
- **PostgreSQL** đang chạy
- **Neo4j** đang chạy (với dữ liệu luật giao thông đã import)
- **Redis** đang chạy

### 1. Clone & cài đặt dependencies

```bash
git clone <repo-url>
cd Chatbot-law

# Backend
cd backend-core
npm install
npx prisma migrate dev    # Tạo bảng trong PostgreSQL
cd ..

# AI Service
cd ai-service
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac
cd ..
```

### 2. Cấu hình biến môi trường

Tạo file `.env` trong `backend-core/` và `ai-service/` theo mẫu ở mục [Biến môi trường](#biến-môi-trường).

### 3. Chạy development server

**Windows (PowerShell) — Mở 2 cửa sổ riêng:**

```powershell
.\dev.ps1
```

**Cross-platform (concurrently) — Chạy trong 1 terminal:**

```bash
npm run dev
```

**Chạy từng service riêng:**

```bash
# NestJS Backend
cd backend-core && npm run dev

# FastAPI AI Service
cd ai-service
.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

### 4. Truy cập

| Service | URL |
|---------|-----|
| NestJS API | http://localhost:8080/api/v1 |
| Swagger Docs | http://localhost:8080/api |
| FastAPI AI | http://localhost:8001 |
| Health Check | http://localhost:8001/health |

---

## Design Patterns

| Pattern | Áp dụng |
|---------|---------|
| **ReAct** (Reasoning + Acting) | Agent suy luận trước khi gọi tool, fallback khi thiếu thông tin |
| **Stateful Checkpointing** | Lưu trạng thái hội thoại multi-turn qua PostgreSQL (thread_id = conversation_id) |
| **Cascading Search** | Knowledge Graph → Web Search (Tier 1 chính phủ → Tier 2 đáng tin) |
| **CASL RBAC** | Phân quyền declarative, tích hợp Prisma |
| **Standardized Response** | Tất cả endpoint trả `{statusCode, message, data}` |
| **Soft Delete** | Conversation & User hỗ trợ xóa mềm |
| **SSE Streaming** | Real-time streaming câu trả lời từ LLM đến client |

---

## License

[MIT](LICENSE)