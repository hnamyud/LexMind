# Chat API

Đường dẫn cơ sở: `/api/v1/chat`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/ask/stream` | `POST` | `JWT Bearer`, `<ConversationOwnerGuard>` | 5 req / 60s | Gửi câu hỏi cho AI và nhận câu trả lời dạng Server-Sent Events (SSE). Body yêu cầu `question` và `conversationId`. |
| `/regenerate/:messageId` | `POST` | `JWT Bearer` | 5 req / 60s | Yêu cầu AI tạo lại (regenerate) câu trả lời cho một tin nhắn lỗi. Cần truyền vào tham số param `messageId`. |
| `/law-detail/:nodeId` | `GET` | `JWT Bearer` | 30 req / 60s | Lấy chi tiết thông tin luật giao thông trực tiếp từ Neo4j Knowledge Graph thông qua ID của node (điều/khoản). |

## Ghi chú
- API `/ask/stream` được phân luồng xử lý chặt chẽ. Backend sẽ Proxy stream dạng NDJSON từ FastAPI (AI service) biến đổi thành chuẩn SSE đến Frontend Client để render typing effect realtime.
- Có giới hạn hạn mức Rate limit khắt khe (5 requests mỗi 60 giây) cho các hành động cần gọi LLM (ask/trả lời) để kiểm soát tài nguyên hệ thống.

---

## 1. POST `/ask/stream` - Gửi câu hỏi và nhận stream response

### Request Body
```json
{
  "question": "Vượt đèn đỏ xe máy bị phạt bao nhiêu?",
  "conversationId": "uuid-conversation-id"
}
```

### Response Format (SSE/NDJSON Stream)

Hệ thống trả về stream NDJSON với các event types sau:

#### 1. Process Events (Trạng thái xử lý)
```json
{
  "type": "process",
  "stage": "route|rewrite|cache|retrieval|reflect|clarify|generate",
  "content": "Đang phân loại câu hỏi..."
}
```

**Stages:**
- `route`: Phân loại câu hỏi (use_tool / direct_answer / absurd_logic / out_of_domain)
- `rewrite`: Chuẩn hóa thuật ngữ pháp lý, xác định query_mode (penalty_lookup / provision_lookup)
- `cache`: Kiểm tra semantic cache
- `retrieval`: Tra cứu Knowledge Graph (Neo4j) hoặc Web Search
- `reflect`: Đánh giá chất lượng context
- `clarify`: Cần làm rõ thêm câu hỏi
- `generate`: Tổng hợp câu trả lời

#### 2. Thinking Events (Suy luận của AI)
```json
{
  "type": "thinking",
  "content": "Đang phân tích điều khoản liên quan..."
}
```

#### 3. Answer Events (Câu trả lời streaming)
```json
{
  "type": "answer",
  "content": "Theo Nghị định 168/2024/NĐ-CP..."
}
```

#### 4. Metrics Event (Cuối stream)
```json
{
  "type": "metrics",
  "content": {
    "model": "gemini-2.0-flash-thinking-exp-01-21",
    "complexityLevel": 2,
    "modelRouter": "gemini-2.0-flash-exp",
    "modelReflector": "gemini-2.0-flash-exp",
    "modelDirect": "gemini-2.0-flash-exp",
    "modelGeneratorL1": "gemini-2.0-flash-exp",
    "modelGeneratorL2": "gemini-2.0-flash-thinking-exp-01-21",
    "modelGeneratorL3": "gemini-2.0-flash-thinking-exp-01-21",
    "ttft": 1250,
    "totalTime": 3500,
    "graphQueryTime": 450,
    "webSearchTime": null,
    "cacheCheckTime": 120,
    "cacheHit": false,
    "inputTokens": 1500,
    "outputTokens": 800,
    "thinkingTokens": 200,
    "toolCalls": 1,
    "toolCallDetails": [
      {
        "tool": "graph_retrieval",
        "duration_ms": 450
      }
    ],
    "cost": 0.00125,
    "error": null,
    "errorType": null,
    "nodeTimings": {
      "routerTime": 250,
      "rewriteTime": 180,
      "cacheCheckTime": 120,
      "retrievalTime": 450,
      "reflectorTime": 300,
      "generatorTime": 2200
    },
    "slowestNode": {
      "node": "generatorTime",
      "durationMs": 2200
    }
  }
}
```

**Metrics Fields:**
- `model`: Model generator thực tế được dùng (theo complexity level)
- `complexityLevel`: 1 (Simple) | 2 (Medium) | 3 (Complex)
- `ttft`: Time To First Token (ms)
- `totalTime`: Tổng thời gian xử lý (ms)
- `cacheHit`: true nếu câu trả lời từ cache
- `inputTokens`, `outputTokens`, `thinkingTokens`: Token usage
- `cost`: Chi phí ước tính (USD)
- `nodeTimings`: Thời gian từng node trong pipeline

#### 5. Metadata Event (Cuối stream)
```json
{
  "type": "metadata",
  "content": {
    "sources": [
      {
        "type": "knowledge_graph",
        "id": "nd168_2024_d7_k7_c",
        "score": 0.95
      },
      {
        "type": "knowledge_graph",
        "id": "l35_2024_dieu_13",
        "score": 0.82
      },
      {
        "type": "web",
        "url": "https://example.com/article",
        "title": "Quy định mới về xử phạt giao thông"
      }
    ],
    "context": "<source id=\"nd168_2024_d7_k7_c\" score=\"0.950\" label=\"Article\" from=\"keyword,vector\">\n  <doc_ref>nd168_2024</doc_ref>\n  <source_title>Nghị định 168/2024/NĐ-CP</source_title>\n  <path>Điều 7 > Khoản 7 > Điểm c</path>\n  <content>c) Không chấp hành hiệu lệnh của đèn tín hiệu giao thông</content>\n  <relationships>...</relationships>\n</source>",
    "reflector_verdict": "sufficient",
    "cacheHit": false,
    "nodeTimings": {
      "routerTime": 250,
      "rewriteTime": 180,
      "retrievalTime": 450
    }
  }
}
```

**Metadata Fields:**
- `sources`: Danh sách nguồn tham khảo
  - `type`: "knowledge_graph" hoặc "web"
  - `id`: Node ID trong Neo4j (format mới: `{doc_ref}_{structure}`)
    - `nd168_2024_d7_k7_c`: Nghị định 168/2024, Điều 7, Khoản 7, Điểm c
    - `l35_2024_dieu_13`: Luật Đường bộ 2024, Điều 13
    - `l36_2024_d5_k2_a`: Luật Trật tự ATGT 2024, Điều 5, Khoản 2, Điểm a
  - `score`: Độ liên quan (0-1)
- `context`: Raw XML context từ Knowledge Graph
  - `<doc_ref>`: Mã văn bản (nd168_2024, l35_2024, l36_2024)
  - `<source_title>`: Tên đầy đủ văn bản
  - `<path>`: Đường dẫn cấu trúc (Chương > Điều > Khoản > Điểm)
- `reflector_verdict`: "sufficient" | "needs_clarification" | "not_found"

#### 6. Done Event
```json
{
  "type": "done"
}
```

---

## 2. Query Modes (Mới)

Hệ thống hiện hỗ trợ 2 query modes:

### penalty_lookup (Câu hỏi về xử phạt)
- Câu hỏi về mức phạt, hậu quả vi phạm
- Entities: `{violation, vehicle_type, subject, conditions[]}`
- Ví dụ: "Vượt đèn đỏ xe máy bị phạt bao nhiêu?"

### provision_lookup (Câu hỏi về quy định/định nghĩa)
- Câu hỏi về định nghĩa, nguyên tắc, quy định
- Entities: `{legal_concept, document_ref, article_ref}`
- Ví dụ: 
  - "Đất của đường bộ là gì?"
  - "Điều 13 khoản 1 điểm a luật đường bộ quy định gì?"
  - "Nguyên tắc tham gia giao thông là gì?"

---

## 3. Supported Documents (Đa văn bản)

Hệ thống hiện hỗ trợ 3 văn bản pháp luật:

| Document Ref | Tên đầy đủ | Loại |
|--------------|------------|------|
| `nd168_2024` | Nghị định 168/2024/NĐ-CP | Nghị định |
| `l35_2024` | Luật Đường bộ 2024 | Luật |
| `l36_2024` | Luật Trật tự, An toàn giao thông đường bộ 2024 | Luật |

---

## 4. Node ID Format (Mới)

Format mới: `{doc_ref}_{structure}`

**Ví dụ:**
- `nd168_2024_d7_k7_c`: Nghị định 168/2024, Điều 7, Khoản 7, Điểm c
- `nd168_2024_d6_k3_p`: Nghị định 168/2024, Điều 6, Khoản 3, Điểm p
- `l35_2024_dieu_13`: Luật Đường bộ 2024, Điều 13 (chỉ điều)
- `l35_2024_d13_k1_a`: Luật Đường bộ 2024, Điều 13, Khoản 1, Điểm a
- `l36_2024_d5_k2`: Luật Trật tự ATGT 2024, Điều 5, Khoản 2

**Pattern:**
- Chỉ điều: `{doc_ref}_dieu_{N}`
- Điều + khoản: `{doc_ref}_d{N}_k{N}`
- Điều + khoản + điểm: `{doc_ref}_d{N}_k{N}_{letter}`

---

## 5. Citation Format (Trích dẫn trong câu trả lời)

Format: `[Điều X, Khoản Y, Điểm Z, <tên_văn_bản>]`

**Ví dụ:**
- `[Điều 7, Khoản 7, Điểm c, Nghị định 168/2024/NĐ-CP]`
- `[Điều 13, Khoản 1, Điểm a, Luật Đường bộ 2024]`
- `[Điều 5, Khoản 2, Luật Trật tự, An toàn giao thông đường bộ 2024]`

---

## 6. Error Handling

### Common Errors
- `404`: Conversation không tồn tại
- `403`: Không có quyền truy cập conversation
- `429`: Vượt quá rate limit
- `500`: Lỗi nội bộ AI service

### Error Response (trong stream)
```json
{
  "type": "thought",
  "content": "❌ Lỗi trong quá trình xử lý: Connection timeout"
}
```
