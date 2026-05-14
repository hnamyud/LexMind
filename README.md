# LexMind — Chatbot Tư Vấn Luật Giao Thông Việt Nam

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-blue.svg)](https://www.typescriptlang.org/)
[![NestJS](https://img.shields.io/badge/NestJS-11-red.svg)](https://nestjs.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)

Hệ thống chatbot AI hỗ trợ tra cứu và tư vấn **Nghị định 168/2024/NĐ-CP** và **Luật Đường bộ 2024**, sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp **Knowledge Graph Neo4j** và **Web Search** để cung cấp câu trả lời chính xác, có trích dẫn nguồn pháp lý. Hệ thống tự động nhận biết ngữ cảnh để phản hồi theo phong cách tự nhiên hoặc chuẩn mực pháp lý.

---

## Mục lục

- [Động lực & Mục tiêu](#động-lực--mục-tiêu)
- [Tính năng nổi bật](#tính-năng-nổi-bật)
- [Kiến trúc hệ thống](#kiến-trúc-hệ-thống)
- [Tech Stack](#tech-stack)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Database Schema](#database-schema)
- [AI Service — RAG Pipeline](#ai-service--rag-pipeline)
- [Benchmark](#benchmark)
- [API Endpoints](#api-endpoints)
- [Hướng dẫn cài đặt & chạy](#hướng-dẫn-cài-đặt--chạy)
- [Chạy bằng Docker](#chạy-bằng-docker)
- [Biến môi trường](#biến-môi-trường)
- [Đóng góp](#đóng-góp)
- [License](#license)

---

## Động lực & Mục tiêu

Luật giao thông Việt Nam thay đổi thường xuyên và có nhiều điều khoản phức tạp khiến người dân khó tra cứu chính xác. Nghị định 168/2024/NĐ-CP với mức phạt mới đã gây ra nhiều thắc mắc trong cộng đồng.

**LexMind** ra đời để:
- Giúp người dân tra cứu mức phạt, quy định giao thông nhanh chóng và chính xác
- Cung cấp câu trả lời có trích dẫn nguồn pháp lý cụ thể, tránh thông tin sai lệch
- Hỗ trợ cả câu hỏi thông thường lẫn câu hỏi pháp lý chuyên sâu qua cùng một giao diện

---

## Tính năng nổi bật

- **Hybrid RAG**: Kết hợp Knowledge Graph (Neo4j) + Vector Search + Web Search để truy xuất thông tin toàn diện
- **LangGraph Agent**: Pipeline ReAct với Router tự động phân loại câu hỏi (pháp lý / đời thường)
- **Streaming Response**: Trả lời theo thời gian thực qua Server-Sent Events
- **Survival Rule**: Reflector tự nhận biết vùng xám pháp lý, tránh phán đoán sai
- **Xác thực đa phương thức**: JWT, Local Auth, Google OAuth, OTP
- **Xử lý Hình Ảnh (Vision)**: Tối ưu hoá tải lên bằng Stream Pipeline qua Sharp (nén WebP thông minh giữ chi tiết viền) và lưu trữ phi tập trung trên Cloudinary để nhận diện tình huống giao thông.
- **Auto-title**: Tự động sinh tiêu đề hội thoại bằng AI sau tin nhắn đầu tiên
- **Feedback Loop**: Like/dislike từng câu trả lời để cải thiện chất lượng

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
│  • Quản lý hội thoại & Chat   │──│  • Neo4j Knowledge Graph     │
│  • File/Image Upload (Stream) │  │  • Web Search (Serper)       │
│  • Event-driven Background    │  │  • Firecrawl Web Scraping    │
│  • RAG & LLM checkpointer     │  │  • PostgreSQL Checkpointer   │
│  • Rate Limiting & Auth       │  │  • Gemini 3.0 Flash & Vision │
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
| LLM Model | Google Gemini (3.0 Flash, 3.1 Flash Lite) | Latest |
| Knowledge Graph | Neo4j | 5.28.1 |
| Embeddings | [DEk21_hcmute_embedding](https://huggingface.co/huyydangg/DEk21_hcmute_embedding) | 4.1.0 |
| Web Search | Serper.dev + Firecrawl | Via SDK |
| State Management | LangGraph AsyncPostgresSaver | 4.0.0 |
| Image Processing | Sharp + Cloudinary | Latest |
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
        ├── api/routes.py       # API endpoints
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

> LangGraph quản lý thêm 4 bảng checkpoint tự động sinh riêng.

---

## AI Service — RAG Pipeline

```text
                     ┌─────────┐
                     │  START  │
                     └────┬────┘
                          ▼
                   ┌──────────────┐
                   │    Router    │ ── Phân loại: Tự nhiên vs Pháp lý
                   └──────┬───────┘
                          ▼
            ┌─────────────┴─────────────┐
            ▼                           ▼
      ┌────────────┐             ┌────────────┐
      │  Natural   │             │   Legal    │◀────────────┐
      │  Agent     │             │   Agent    │             │
      └────────────┘             └──────┬─────┘             │
            │                          │ (ReAct Reasoning)  │
            │                          ▼                    │
            │                   ┌──────────────┐            │
            │                   │    Tools     │────────────┘
            │                   │ (Neo4j, Web) │
            │                   └──────┬───────┘
            │                          ▼
            │                   ┌──────────────┐
            │                   │  Reflector   │ ── Kiểm tra chất lượng + Survival Rule
            │                   └──────────────┘
            └─────────────┬─────────────┘
                          ▼
                   ┌──────────────┐
                   │  Synthesis   │ ── Kết xuất chuẩn form pháp lý
                   └──────────────┘
```

**Các cơ chế chính:**

- **Router**: Tự động gán `response_style="legal"` hoặc `"natural"`. Câu hỏi giao tiếp thường ngày sẽ được xử lý nhẹ nhàng hơn qua `synthesis_natural.yaml`.
- **Survival Rule**: Khi gặp tình huống chưa có quy định rõ ràng, Reflector kích hoạt cơ chế tự vệ — suy luận tìm luật gần nhất hoặc thừa nhận vùng xám thay vì phán đoán sai.
- **Event-Driven Auto-title**: Sau tin nhắn đầu, NestJS phát sự kiện `conversation.title_needed`. `TitleGeneratorService` chạy nền gọi AI Service để sinh tên phiên và lưu DB một cách trong suốt.

---

## Benchmark

Benchmark được thực hiện trên bộ dataset **80 câu hỏi** , chia thành 8 session, mỗi session 10 câu. Các chỉ số được chấm theo thang điểm `0.0` đến `1.0`, riêng latency tính bằng giây.

### Tổng quan kết quả

| Chỉ số | Điểm |
|--------|------|
| Behavior compliance | **0.9500** |
| Groundedness | **0.9469** |
| Correctness | **0.7844** |
| Retrieval node match | **0.6299** |
| Citation accuracy | **0.5719** |
| Latency trung bình | **16.04s** |

### Kết quả theo session

| Session | Behavior compliance | Citation accuracy | Correctness | Groundedness | Retrieval node match | Latency (s) |
|---------|---------------------|-------------------|-------------|--------------|----------------------|-------------|
| 1 -> 10 | 1.0000 | 0.6500 | 0.8500 | 1.0000 | 0.5750 | 12.06 |
| 11 -> 20 | 1.0000 | 0.8000 | 0.9000 | 0.9500 | 0.8330 | 14.38 |
| 21 -> 30 | 1.0000 | 0.6750 | 0.9250 | 0.8750 | 0.6830 | 13.41 |
| 31 -> 40 | 0.9000 | 0.6000 | 0.6500 | 0.9500 | 0.6000 | 11.73 |
| 41 -> 50 | 1.0000 | 0.5000 | 0.8250 | 1.0000 | 0.7170 | 23.59 |
| 51 -> 60 | 0.9000 | 0.4750 | 0.6500 | 1.0000 | 0.6480 | 17.18 |
| 61 -> 70 | 0.9000 | 0.3750 | 0.7250 | 0.8500 | 0.3930 | 17.20 |
| 71 -> 80 | 0.9000 | 0.5000 | 0.7500 | 0.9500 | 0.5900 | 18.76 |
| **Trung bình** | **0.9500** | **0.5719** | **0.7844** | **0.9469** | **0.6299** | **16.04** |

---

## API Endpoints

### Authentication — `/api/v1/auth`

Hỗ trợ Register, Login (JWT & Local), SSO (Google OAuth), xác minh OTP để đổi mật khẩu.

### Chat — `/api/v1/chat`

| Method | Endpoint | Mô tả | Guard |
|--------|----------|--------|-------|
| POST | `/ask/stream` | Stream trả lời từ AI qua Server-Sent Events | JWT |
| POST | `/regenerate/:messageId` | Xóa checkpoint lỗi, yêu cầu AI sinh lại | JWT |
| GET | `/law-detail/:nodeId` | Lấy chi tiết điều luật từ Neo4j | JWT |

### AI Service (Internal) — `http://127.0.0.1:8001`

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| POST | `/ask/stream` | Core RAG streaming |
| POST | `/conversations/generate-title` | Sinh tựa đề hội thoại |
| DELETE | `/conversations/{id}/checkpoints` | Xóa bộ nhớ checkpoint |

**Chuẩn response API:**
```json
{
  "statusCode": 200,
  "message": "Thành công!",
  "data": { ... }
}
```

---

## Hướng dẫn cài đặt & chạy

### Yêu cầu

- Node.js >= 18
- Python >= 3.11
- Docker (để chạy Neo4j, PostgreSQL, Redis)

### 1. Clone repository

```bash
git clone https://github.com/your-username/lexmind.git
cd lexmind
```

### 2. Cài đặt dependencies

```bash
# Root (concurrently)
npm install

# Backend-Core
cd backend-core && npm install

# AI Service
cd ../ai-service && pip install -r requirements.txt
```

### 3. Cấu hình biến môi trường

Tạo file `.env` theo mẫu ở mục [Biến môi trường](#biến-môi-trường) cho cả 2 service.

### 4. Khởi động services

```powershell
# Windows
.\dev.ps1
```

```bash
# Linux / macOS
npm run dev
```

Sau khi khởi động:
- Backend API: `http://localhost:8080/api/v1`
- AI Service: `http://localhost:8001`

---

## Chạy bằng Docker

Repo có 2 image runtime chính:

| Service | Image tag gợi ý | Port |
|---------|------------------|------|
| AI Service | `chatbot-law-ai:optimized` | `8001` |
| Backend Core | `chatbot-law-backend:optimized` | `8080` |

### Chuẩn bị `.env`

Tạo file `.env` ở root project từ `.env.example`, sau đó cấu hình các biến cloud/local cần thiết:

```powershell
Copy-Item .env.example .env
```

Các biến quan trọng khi chạy Docker:

```env
PORT=8080
FASTAPI_PORT=8001

# Backend gọi AI qua Docker network, không dùng localhost trong container.
FASTAPI_URL=chatbot-law-ai-test

# Nếu dùng model host local trên máy dev, container phải gọi host.docker.internal.
BASE_URL=http://host.docker.internal:20128/v1

# Redis Stack trong Docker network.
REDIS_HOST=chatbot-law-redis-test
REDIS_PORT=6379
REDIS_URL=redis://chatbot-law-redis-test:6379
```

> Lưu ý: Docker `--env-file` không parse dấu quote giống `python-dotenv`. Nếu `.env` đang có dạng `KEY="value"`, nên dùng file env tạm đã bỏ quote như ví dụ bên dưới.

### Build image

Chạy từ root project:

```powershell
docker build -t chatbot-law-ai:optimized ./ai-service
docker build -t chatbot-law-backend:optimized ./backend-core
```

Kích thước tham khảo sau tối ưu:

| Image | Size tham khảo |
|-------|----------------|
| `chatbot-law-ai:optimized` | khoảng `485MB` |
| `chatbot-law-backend:optimized` | khoảng `135MB` |

### Run stack test bằng Docker

Tạo Docker network:

```powershell
docker network create chatbot-law-run
```

Tạo env file tạm tương thích Docker từ `.env` root:

```powershell
$tmp = Join-Path $env:TEMP 'chatbot-law-docker.env'
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*$' -or $_ -match '^\s*#' -or $_ -notmatch '=') {
    $_
  } else {
    $parts = $_.Split('=', 2)
    $key = $parts[0]
    $value = $parts[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    "$key=$value"
  }
} | Set-Content -Encoding ascii $tmp
```

Chạy Redis Stack, AI Service, Backend Core:

```powershell
docker run -d `
  --name chatbot-law-redis-test `
  --network chatbot-law-run `
  -p 6379:6379 `
  redis/redis-stack-server:latest

docker run -d `
  --name chatbot-law-ai-test `
  --network chatbot-law-run `
  --env-file $tmp `
  -e REDIS_URL=redis://chatbot-law-redis-test:6379 `
  -e FASTAPI_URI=0.0.0.0 `
  -p 8001:8001 `
  chatbot-law-ai:optimized

docker run -d `
  --name chatbot-law-backend-test `
  --network chatbot-law-run `
  --env-file $tmp `
  -e FASTAPI_URL=chatbot-law-ai-test `
  -e FASTAPI_PORT=8001 `
  -e REDIS_HOST=chatbot-law-redis-test `
  -e REDIS_PORT=6379 `
  -e REDIS_URL=redis://chatbot-law-redis-test:6379 `
  -p 8080:8080 `
  chatbot-law-backend:optimized
```

Kiểm tra trạng thái:

```powershell
docker ps --filter "name=chatbot-law-.*-test"
Invoke-RestMethod http://localhost:8001/health
```

Kết quả AI health kỳ vọng:

```json
{
  "status": "healthy",
  "neo4j_connected": true,
  "gemini_configured": true,
  "embed_model_loaded": true,
  "cache_connected": true
}
```

Endpoints sau khi chạy:

- AI Service: `http://localhost:8001`
- AI health: `http://localhost:8001/health`
- Backend API: `http://localhost:8080`
- Swagger UI: `http://localhost:8080/docs`

### Dừng stack test

```powershell
docker rm -f chatbot-law-ai-test chatbot-law-backend-test chatbot-law-redis-test
```

### Chạy bằng Docker Compose

Có thể dùng Compose để build/run nhanh:

```powershell
docker compose up --build
```

Nếu cần semantic cache đầy đủ cho pipeline, dùng Redis Stack thay cho Redis thường trong Compose:

```yaml
redis:
  image: redis/redis-stack-server:latest
```

---

## Đóng góp

Mọi đóng góp đều được hoan nghênh! Để đóng góp:

1. Fork repository này
2. Tạo branch mới: `git checkout -b feature/ten-tinh-nang`
3. Commit thay đổi: `git commit -m 'feat: mô tả ngắn gọn'`
4. Push lên branch: `git push origin feature/ten-tinh-nang`
5. Mở Pull Request

Vui lòng đảm bảo code đã được test trước khi tạo PR.

---

## License

[MIT](LICENSE) © 2026 LexMind Team
