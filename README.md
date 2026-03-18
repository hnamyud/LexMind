# Chatbot Luật Giao Thông Việt Nam 🇻🇳

Hệ thống chatbot hỗ trợ tra cứu và tư vấn luật giao thông Việt Nam (Nghị định 168/2024/NĐ-CP), sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp **Knowledge Graph** và **Web Search** để cung cấp câu trả lời chính xác, có trích dẫn nguồn. Hệ thống cũng có khả năng nhận biết ngữ cảnh để trả lời tự nhiên (natural) hoặc chuẩn mực pháp lý (legal).

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

```text
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
│  • Event-driven Background    │  │  • PostgreSQL Checkpointer   │
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
| **backend-core** | TypeScript | NestJS 11 | 8080 | API gateway, auth, quản lý hội thoại, event bus |
| **ai-service** | Python | FastAPI | 8001 | RAG pipeline, LLM reasoning, tìm kiếm |

---

## Tech Stack

| Thành phần | Công nghệ | Phiên bản |
|------------|-----------|-----------|
| Backend Framework | NestJS | 11.0.1 |
| ORM | Prisma | 7.4.2 |
| Authentication | Passport (JWT, Local, Google OAuth) | 0.7.0 |
| Authorization | CASL | 6.7.3 |
| Event Bus | NestJS Event Emitter | 3.0.0 |
| Cache & Queue | Redis (ioredis) | 5.10.0 |
| AI Framework | FastAPI | 0.115.9 |
| LLM Orchestration | LangGraph | 1.0.9 |
| LLM Model | Google Gemini 2.5 Flash | Latest |
| Knowledge Graph | Neo4j | 5.28.1 |
| Embeddings | SentenceTransformers (vietnamese-sbert) | 4.1.0 |
| Web Search | Serper.dev + Firecrawl | Via SDK |
| State Management | LangGraph AsyncPostgresSaver | 4.0.0 |
| Security | Helmet, bcryptjs | 8.1.0 / 2.4.3 |

---

## Cấu trúc thư mục

```text
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
│       │   ├── chat/           # Stream proxy, Auto-title event listening
│       │   ├── conversations/  # CRUD hội thoại
│       │   ├── messages/       # Lịch sử tin nhắn
│       │   ├── feedbacks/      # Like/dislike câu trả lời
│       │   └── users/          # Quản lý người dùng
│       └── shared/             # Cache, Mailer
│
└── ai-service/                 # FastAPI AI Server
    ├── main.py                 # Entry point (port 8001)
    └── app/
        ├── api/routes.py       # API endpoints (bao gồm /conversations/generate-title)
        ├── core/               # Checkpoint, State schema
        ├── services/
        │   └── rag_service.py  # RAG pipeline & LangGraph graph
        ├── prompts/            # System prompts (YAML)
        │   ├── synthesis.yaml
        │   ├── synthesis_natural.yaml
        │   ├── reflector.yaml
        │   ├── analyzer.yaml
        │   ├── router_rewrite.yaml
        │   └── title_generator.yaml
        └── tools/              # Vector search, Web Search
```

---

## Database Schema

### PostgreSQL (Prisma)

```text
┌──────────┐     1:N     ┌──────────────┐     1:N     ┌──────────┐
│   User   │────────────▶│ Conversation │────────────▶│ Message  │
│          │             │              │             │          │
│ id (UUID)│             │ id (UUID)    │             │ id (UUID)│
│ email    │             │ userId (FK)  │             │ parentId │
│ password │             │ title        │             │ convId   │
│ fullName │             │ summary      │             │ sender   │
│ role     │             │ isDeleted    │             │ content  │
│          │             │ deletedAt    │             │ thought  │
│          │             │              │             │ metadata │
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
| **User** | Tài khoản người dùng. Hỗ trợ soft-delete. |
| **Conversation** | Phiên hội thoại. Chứa tựa đề do AI tự động sinh ra. |
| **Message** | Tin nhắn (`user` / `bot`). Lưu suy luận vào `thought`. `metadata` lưu nguồn tham khảo (URL, tiêu đề web, trích dẫn). |
| **Feedback** | Đánh giá tính hữu ích của câu trả lời. |

Ngoài ra, LangGraph kiểm soát 4 bảng checkpoint tự động sinh.

---

## AI Service — RAG Pipeline

### Kiến trúc LangGraph nâng cao

```text
                     ┌─────────┐
                     │  START  │
                     └────┬────┘
                          ▼
                   ┌──────────────┐
                   │    Router    │ (Phân loại: Tự nhiên vs Pháp lý)
                   └──────┬───────┘
                          ▼
            ┌─────────────┴─────────────┐
            ▼                           ▼
      ┌────────────┐             ┌────────────┐
      │  Natural   │             │   Legal    │
      │  Agent     │             │   Agent    │◀────────────┐
      └────────────┘             └──────┬─────┘             │
            │                           │ (Reasoning)       │
            │                           ▼                   │
            │                    ┌──────────────┐           │
            │                    │    Tools     │───────────┘
            │                    │ (Neo4j, Web) │
            │                    └──────┬───────┘
            │                           ▼
            │                    ┌──────────────┐
            │                    │  Reflector   │ (Kiểm tra chất lượng, Survival rule)
            │                    └──────────────┘
            └─────────────┬─────────────┘
                          ▼
                   ┌──────────────┐
                   │  Synthesis   │ (Kết xuất chuẩn form)
                   └──────────────┘
```

### Response Tags & Survival Rule

- **Router**: Tự động đánh URL `response_style="legal"` hoặc `"natural"`. Nếu là câu hỏi giao tiếp đời thường, bot trả lời thân thiện (sử dụng `synthesis_natural.yaml`).
- **Reflector + Survival Rule**: Khi phải đối mặt với các tình huống mới chưa có quy định, hệ thống kích hoạt tự vệ (survival rule) để suy luận tìm luật gần nhất hoặc thừa nhận nếu đó là vùng xám, tránh phán bừa.

---

## Backend Core — NestJS API

Backend-Core giờ đây kết hợp kiến trúc **Event-Driven**:

- **Tự động sinh tiêu đề**: Khi một hội thoại mới diễn ra, ChatService kích hoạt sự kiện `conversation.title_needed`. `TitleGeneratorService` (chạy nền) sẽ lấy câu hỏi gọi sang AI Service `POST /conversations/generate-title` để sinh tên phiên và lưu DB một cách trong suốt (`@nestjs/event-emitter`).

### Các Response tiêu chuẩn
Chuẩn hóa API với định dạng: `{ "statusCode": 200, "message": "Thành công!", "data": { ... } }`

---

## API Endpoints

### Authentication & Config — `/api/v1/auth`
| Các API hỗ trợ Register, Login bằng JWT & Local, SSO bằng Google OAuth, và xác minh OTP phục vụ đổi password. |

### Chat — `/api/v1/chat`
| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| POST | `/ask/stream` | Stream trả lời từ AI theo Server-Sent Events | JWT |
| POST | `/regenerate/:messageId` | Xóa checkpoint lỗi, yêu cầu AI sinh lại | JWT |
| GET | `/law-detail/:nodeId` | Lấy chi tiết luật giao thông từ Neo4j | JWT |

### AI Service (Internal) — `http://127.0.0.1:8001`
Bao gồm các endpoint phục vụ backend-core:
| Method | Endpoint | Mô tả |
|--------|----------|--------|
| POST | `/ask/stream` | Core RAG streaming |
| POST | `/conversations/generate-title`| Sinh tựa đề cho Conversation |
| DELETE | `/conversations/{id}/checkpoints` | Xóa bộ nhớ | 

---

## Luồng hoạt động nổi bật

### Hỏi đáp có Streaming
1. Client gọi RESTful `/chat/ask/stream`.
2. NestJS Auth + Rate Lmit chặn / pass, sau đó lưu tin nhắn user.
3. NestJS gọi Stream xuống AI Service FastAPI.
4. AI đánh giá (Router) -> Xử lý chuỗi (Legal/Natural) -> Tools (Search) -> Reflector.
5. FastAPI trả chuỗi NDJSON (type: thought, answer, metadata).
6. NestJS Proxy lại thành Server-Sent Events về cho Frontend.
7. Khi "done", NestJS lưu tin nhắn bot và thông tin metadata (Web urls).
8. NestJS kích hoạt **Event** sinh tiêu đề nếu là tin nhắn đầu.

---

## Biến môi trường

*(Xem README cũ để biết chi tiết biến môi trường giống như trước)*

## Hướng dẫn cài đặt & chạy
Sử dụng script `dev.ps1` ở thư mục root để start cả 2 services cùng một lúc.
```powershell
.\dev.ps1
```
Hoặc `npm run dev` thông qua root `package.json` trên nền tảng khác.

## License

[MIT](LICENSE)