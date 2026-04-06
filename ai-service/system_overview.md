# AI Service API Reference

Base URL: `http://127.0.0.1:8001`  
Internal service — chỉ nhận request từ `backend-core`. Mọi endpoint yêu cầu header `X-Internal-Secret`.

---

## Authentication

Tất cả endpoint đều yêu cầu header sau:

```
X-Internal-Secret: <secret>
```

Giá trị phải khớp với biến môi trường `X_INTERNAL_SECRET` được cấu hình cho cả `ai-service` và `backend-core`. Request thiếu header này sẽ nhận `403 Forbidden`.

---

## Endpoints

- [POST /ask/stream](#post-askstream)
- [POST /conversations/generate-title](#post-conversationsgenerate-title)
- [DELETE /conversations/{id}/checkpoints](#delete-conversationsidcheckpoints)
- [GET /law-detail/{node_id}](#get-law-detailnode_id)
- [GET /health](#get-health)
- [GET /debug](#get-debug)
- [DELETE /cache](#delete-cache)

---

## POST /ask/stream

Core RAG pipeline. Nhận câu hỏi của người dùng, chạy qua toàn bộ pipeline (Router → Legal/Natural Agent → Reflector → Synthesis) và stream kết quả về theo định dạng NDJSON.

### Request

**Headers**

| Header | Required | Description |
|--------|----------|-------------|
| `X-Internal-Secret` | Yes | Internal auth secret |
| `Content-Type` | Yes | `application/json` |

**Body**

```json
{
  "question": "Không đội mũ bảo hiểm bị phạt bao nhiêu?",
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "message_id": "7cb12a90-1234-4abc-9def-000000000001",
  "user_id": "a1b2c3d4-0000-0000-0000-ffffffffffff"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | Yes | Câu hỏi gốc của người dùng |
| `conversation_id` | string (UUID) | Yes | ID phiên hội thoại — dùng làm thread ID cho LangGraph checkpoint |
| `message_id` | string (UUID) | Yes | ID tin nhắn hiện tại |
| `user_id` | string (UUID) | Yes | ID người dùng |

### Response

Response là **NDJSON stream** (newline-delimited JSON). Mỗi dòng là một JSON object độc lập, kết thúc bằng `\n`.

**Stream event types**

| `type` | Mô tả | Xuất hiện |
|--------|--------|-----------|
| `thought` | Quá trình suy luận nội bộ của LLM | 0..N lần |
| `answer` | Chunk nội dung câu trả lời | 1..N lần |
| `metadata` | Danh sách nguồn tham khảo | 1 lần, sau `answer` |
| `metrics` | Token usage và latency | 1 lần |
| `done` | Báo hiệu kết thúc stream | 1 lần, cuối cùng |
| `error` | Lỗi pipeline | 0..1 lần |

**Ví dụ stream thực tế**

```
{"type": "thought", "content": "Phân tích câu hỏi: người dùng hỏi về mức phạt không đội mũ bảo hiểm..."}
{"type": "thought", "content": "Tìm kiếm trong Knowledge Graph với query đã rewrite..."}
{"type": "answer", "content": "Theo Nghị định 168/2024/NĐ-CP, hành vi không đội mũ bảo hiểm"}
{"type": "answer", "content": " khi điều khiển xe máy sẽ bị xử phạt như sau:\n\n- **Mức phạt tiền:** 400.000 – 600.000 VNĐ\n- **Hình thức bổ sung:** Không có\n\nQuy định áp dụng cho cả người lái và người ngồi sau."}
{"type": "metadata", "sources": [{"url": "https://example.gov.vn/nd168", "title": "Nghị định 168/2024/NĐ-CP", "citation": "Điều 6, Khoản 1, Điểm a"}]}
{"type": "metrics", "tokens": {"input": 210, "output": 145, "thinking": 512}, "latency_ms": 1840, "cache_hit": false}
{"type": "done"}
```

**Schema từng event**

`thought`
```json
{
  "type": "thought",
  "content": "string"
}
```

`answer`
```json
{
  "type": "answer",
  "content": "string"
}
```

`metadata`
```json
{
  "type": "metadata",
  "sources": [
    {
      "url": "string | null",
      "title": "string",
      "citation": "string"
    }
  ]
}
```

`metrics`
```json
{
  "type": "metrics",
  "tokens": {
    "input": "integer",
    "output": "integer",
    "thinking": "integer"
  },
  "latency_ms": "integer",
  "cache_hit": "boolean"
}
```

`error`
```json
{
  "type": "error",
  "code": "string",
  "message": "string"
}
```

### Lỗi

| HTTP Status | Mô tả | Cách xử lý |
|-------------|--------|------------|
| `403` | Sai hoặc thiếu `X-Internal-Secret` | Kiểm tra biến môi trường |
| `422` | Body không hợp lệ (thiếu field bắt buộc) | Kiểm tra schema request |
| `500` | Lỗi nội bộ pipeline | Xem log, kiểm tra kết nối Neo4j/Redis |

> Lỗi xảy ra **sau khi stream đã bắt đầu** sẽ được gửi dưới dạng event `{"type": "error", ...}` thay vì HTTP error code.

---

## POST /conversations/generate-title

Sinh tiêu đề ngắn gọn cho một phiên hội thoại dựa trên câu hỏi đầu tiên. Được `backend-core` gọi tự động theo cơ chế event-driven sau tin nhắn đầu tiên trong mỗi conversation.

### Request

**Body**

```json
{
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "first_question": "Không đội mũ bảo hiểm bị phạt bao nhiêu?"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_id` | string (UUID) | Yes | ID phiên hội thoại cần đặt tên |
| `first_question` | string | Yes | Câu hỏi đầu tiên của người dùng trong phiên |

### Response

**200 OK**

```json
{
  "title": "Mức phạt không đội mũ bảo hiểm",
  "generated_at": "2024-04-02T13:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Tiêu đề ngắn (tối đa ~60 ký tự) được sinh bởi LLM |
| `generated_at` | string (ISO 8601) | Thời điểm sinh tiêu đề |

### Lỗi

| HTTP Status | Mô tả |
|-------------|--------|
| `403` | Sai `X-Internal-Secret` |
| `422` | Thiếu `conversation_id` hoặc `first_question` |
| `500` | LLM timeout hoặc lỗi nội bộ |

---

## DELETE /conversations/{id}/checkpoints

Xóa toàn bộ LangGraph checkpoint của một phiên hội thoại. Thường được gọi khi người dùng yêu cầu "Tạo cuộc trò chuyện mới" hoặc khi pipeline gặp lỗi cần reset.

### Request

**Path Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string (UUID) | Yes | `conversation_id` cần xóa checkpoint |

**Ví dụ**

```
DELETE /conversations/3fa85f64-5717-4562-b3fc-2c963f66afa6/checkpoints
X-Internal-Secret: your_secret
```

### Response

**200 OK**

```json
{
  "success": true,
  "deleted_count": 5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` nếu xóa thành công |
| `deleted_count` | integer | Số checkpoint đã xóa. `0` nếu conversation không có checkpoint. |

### Lỗi

| HTTP Status | Mô tả |
|-------------|--------|
| `403` | Sai `X-Internal-Secret` |
| `500` | Lỗi kết nối PostgreSQL checkpoint store |

---

## GET /law-detail/{node_id}

Lấy chi tiết một node điều luật từ Neo4j Knowledge Graph. Dùng để hiển thị thông tin chi tiết khi người dùng click vào trích dẫn trong câu trả lời.

### Request

**Path Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_id` | string | Yes | ID của node trong Neo4j (ví dụ: `dieu_khoan_168_dieu6_khoan1`) |

**Ví dụ**

```
GET /law-detail/dieu_khoan_168_dieu6_khoan1
X-Internal-Secret: your_secret
```

### Response

**200 OK**

```json
{
  "id": "dieu_khoan_168_dieu6_khoan1",
  "type": "dieu_khoan_node",
  "content": "Điều 6. Vi phạm quy định về người điều khiển phương tiện tham gia giao thông đường bộ...",
  "related_penalties": [
    {
      "amount": "400.000 – 600.000 VNĐ",
      "description": "Phạt tiền đối với người không đội mũ bảo hiểm khi điều khiển xe máy"
    }
  ],
  "source_document": "Nghị định 168/2024/NĐ-CP",
  "effective_date": "2025-01-01"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Node ID trong Neo4j |
| `type` | string | Loại node: `dieu_khoan_node`, `action_node`, v.v. |
| `content` | string | Nội dung điều khoản |
| `related_penalties` | array | Danh sách mức phạt liên quan |
| `source_document` | string | Văn bản pháp lý nguồn |
| `effective_date` | string | Ngày có hiệu lực |

### Lỗi

| HTTP Status | Mô tả | Cách xử lý |
|-------------|--------|------------|
| `403` | Sai `X-Internal-Secret` | Kiểm tra header |
| `404` | Node không tồn tại trong Neo4j | Kiểm tra lại `node_id` từ metadata |
| `500` | Lỗi kết nối Neo4j | Kiểm tra Neo4j đang chạy |

---

## GET /health

Kiểm tra trạng thái kết nối của tất cả external services. Dùng cho health check, monitoring, hoặc debug khi service bị lỗi.

### Request

Không có body hay parameter.

```
GET /health
X-Internal-Secret: your_secret
```

### Response

**200 OK** — Tất cả services hoạt động bình thường

```json
{
  "status": "healthy",
  "services": {
    "neo4j": "connected",
    "redis": "connected",
    "postgres": "connected"
  },
  "uptime_seconds": 12345.67
}
```

**503 Service Unavailable** — Một hoặc nhiều service không kết nối được

```json
{
  "status": "degraded",
  "services": {
    "neo4j": "connected",
    "redis": "disconnected",
    "postgres": "connected"
  },
  "uptime_seconds": 9876.10
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"healthy"` hoặc `"degraded"` |
| `services` | object | Trạng thái từng dependency |
| `uptime_seconds` | float | Số giây service đã chạy kể từ khi khởi động |

---

## GET /debug

Trả về thông tin cấu hình hiện tại và thống kê runtime. Chỉ dùng trong quá trình phát triển và debug — không expose endpoint này ra môi trường production.

### Response

**200 OK**

```json
{
  "config": {
    "neo4j_uri": "bolt://localhost:7687",
    "redis_url": "redis://localhost:6379",
    "embed_model": "sentence-transformers/nli-mpnet-base-v2",
    "langsmith_tracing": false
  },
  "cache_stats": {
    "hit_rate": 0.35,
    "total_queries": 1500,
    "cache_hits": 525
  },
  "neo4j_stats": {
    "node_count": 5234,
    "relationship_count": 8901
  }
}
```

---

## DELETE /cache

Xóa toàn bộ semantic cache trong Redis. Thực hiện khi dữ liệu trong Knowledge Graph được cập nhật và cần invalidate cache cũ.

> **Cảnh báo:** Thao tác này không thể hoàn tác. Sau khi xóa, tất cả request sẽ phải gọi LLM đầy đủ cho đến khi cache được warm up lại.

### Response

**200 OK**

```json
{
  "success": true,
  "cleared_keys": 342
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` nếu xóa thành công |
| `cleared_keys` | integer | Số lượng cache entry đã bị xóa |

### Lỗi

| HTTP Status | Mô tả |
|-------------|--------|
| `403` | Sai `X-Internal-Secret` |
| `500` | Lỗi kết nối Redis |

---

## Error Reference

Bảng tổng hợp các mã lỗi pipeline trả về qua event `{"type": "error"}` trong stream:

| `code` | Mô tả | Nguyên nhân phổ biến |
|--------|--------|----------------------|
| `NEO4J_TIMEOUT` | Query Neo4j bị timeout | Neo4j quá tải hoặc query phức tạp |
| `LLM_RATE_LIMIT` | Gemini API rate limit | Gọi quá nhiều request/phút |
| `LLM_TIMEOUT` | LLM không phản hồi trong 30s | Thinking budget quá lớn hoặc network lag |
| `RETRIEVAL_EMPTY` | Không tìm được document nào | Knowledge Graph chưa có dữ liệu phù hợp |
| `CHECKPOINT_FAIL` | Không lưu được LangGraph state | Lỗi kết nối PostgreSQL checkpoint store |

---

## Xử lý stream phía client

Ví dụ xử lý NDJSON stream trong JavaScript:

```javascript
const response = await fetch('http://127.0.0.1:8001/ask/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Internal-Secret': process.env.X_INTERNAL_SECRET,
  },
  body: JSON.stringify({
    question: 'Không đội mũ bảo hiểm bị phạt bao nhiêu?',
    conversation_id: crypto.randomUUID(),
    message_id: crypto.randomUUID(),
    user_id: 'user-uuid-here',
  }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const lines = decoder.decode(value).split('\n').filter(Boolean);

  for (const line of lines) {
    const event = JSON.parse(line);

    switch (event.type) {
      case 'thought':
        console.log('[Thinking]', event.content);
        break;
      case 'answer':
        process.stdout.write(event.content); // Stream trực tiếp ra UI
        break;
      case 'metadata':
        console.log('[Sources]', event.sources);
        break;
      case 'metrics':
        console.log('[Metrics]', event);
        break;
      case 'error':
        console.error('[Error]', event.code, event.message);
        break;
      case 'done':
        console.log('\n[Stream ended]');
        break;
    }
  }
}
```

---