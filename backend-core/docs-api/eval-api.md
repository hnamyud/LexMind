# API Docs: Đánh giá Chatbot (Eval Module)

Hệ thống cung cấp một API proxy (NestJS gọi sang AI Backend FastAPI) để thực hiện Flow chấm điểm manual evaluation và scoring cho Chatbot.

Endpoint Context: `http://localhost:8080/eval`

## 1. GET `/eval/datasets`
Lấy danh sách các file dataset hiện có (đuôi `.json`) trong thư mục dataset của hệ thống, cùng với danh sách các nguồn tài liệu (source docs) có trong dataset đó, cho phép admin chọn file và nguồn để chạy.

### Response (200 OK):
```json
{
  "datasets": [
    {
      "name": "nd_168_case.json",
      "source_docs": ["nd168_2024", "luat_gtdb_2008"]
    }
  ],
  "dataset_names": [
    "nd_168_case.json",
    "other_test_data.json"
  ]
}
```

---

## 2. POST `/eval/run-batch`
Khởi động một chu trình chạy đánh giá RAG theo dataset (Batch Evaluation). Quá trình diễn ra trên AI Backend bằng LangSmith / LangGraph và chạy background.

### Payload Model (JSON):
```json
{
  "dataset": "nd_168_case.json", // Optional: Mặc định dataset đầu tiên tìm thấy
  "source_doc": "nd168_2024",    // Optional: Lọc các câu hỏi đánh giá theo nguồn tài liệu
  "concurrency": 1,              // Optional: Số lượng job song song (Mặc định: 1 để an toàn nhất cho eval, tối đa: 10)
  "limit": 5,                    // Optional: Chạy tối đa N câu (null=chạy tất cả)
  "random_sample": true,         // Optional: True = bốc ngẫu nhiên N câu; False = lấy tuần tự từ đầu
  "offset": 0,                   // Optional: Bỏ qua N câu đầu (Chỉ tác dụng khi random_sample=false)
  "question_ids": ["q001"]       // Optional: Chọn lọc chạy theo list ID (Nếu có sẽ bỏ qua limit/offset/random)
}
```

### Response (201 Created):
```json
{
  "status": "started",
  "project_name": "lexmind-12691999",
  "experiment_id": "lexmind-12691999-nd_168_case-...",
  "session_id": "8b5d38db-1300-47bf-af7c-500e318d1f7e",
  "dataset": "nd_168_case.json",
  "total": 5,
  "langsmith_url": "https://smith.langchain.com/o/.../projects/p/...",
  "message": "Batch đã bắt đầu. Xem real-time tại Langsmith URL (đính kèm)."
}
```

> **Lưu ý:** Sau khi LangSmith evaluate hoàn tất, hệ thống **tự động sync kết quả** (answer, context, scores từ AI evaluators) vào bảng `eval_runs`. Kết quả có thể xem qua `GET /eval/results/:sessionId`. Các scores từ LangSmith được map trực tiếp 1:1 như sau:
> - `correctness` → `score_correctness` (BOOLEAN)
> - `groundedness` → `score_groundedness` (BOOLEAN)
> - `behavior_compliance` → `score_behavior` (BOOLEAN)
> - `citation_accuracy` → `score_citation` (BOOLEAN)
> - `retrieval_node_match` → `retrieval_hit_rate` (FLOAT: `0.0 - 1.0`)

---

## 3. GET `/eval/sessions?limit=20`
Lấy danh sách các session đánh giá gần đây. Hiện tại các session được log kèm thông tin Langsmith tracking.

### Request Params
- `limit` (Optional): Số lượng records (default: 20)

### Response (200 OK)
```json
{
  "sessions": [
    {
      "id": "8b5d38db-1300-47bf-af7c-500e318d1f7e",
      "dataset": "nd_168_case.json",
      "source_doc": "nd168_2024",
      "created_at": "2026-03-31T12:00:00.000Z",
      "status": "done",
      "total": 62,
      "completed": 62,
      "project_name": "eval_nd_168_case_1711972800",
      "experiment_id": "8b5d38db-1300-47bf-af7c-500e318d1f7e",
      "langsmith_url": "https://smith.langchain.com/o/.../projects/p/...",
      "progress_pct": 100.0
    }
  ]
}
```

---

## 4. GET `/eval/results/:sessionId`
Lấy kết quả đánh giá của session — bao gồm câu trả lời AI, context đã retrieve, và scores từ LangSmith AI evaluators (auto-filled sau khi batch hoàn tất).

### Response (200 OK)
```json
{
  "session": { "id": "...", "status": "done", "total": 5, "completed": 5 },
  "runs": [
    {
      "id": "09180746-1e0e-473d-82d8-21d45bc83dc9",
      "question_id": "q001",
      "question": "Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?",
      "ground_truth": "Theo quy định tại Điều 7... phạt từ 4 đến 6 triệu...",
      "reference_nodes": ["d7_k7_c", "d7_k10_b", "d7_k13_b", "d7_k13_d"],
      "retrieved_nodes": ["d7_k7_c"],
      "ai_answer": "Chào bạn, vượt đèn đỏ...",
      "context_text": "--- Nguồn d7_k7_c ...",
      "question_type": "factual",
      "expected_behavior": "answer",
      // LangSmith AI Evaluator scores:
      "score_correctness":  true,   // câu trả lời đúng pháp lý không?
      "score_groundedness": true,   // có hallucinate không?
      "score_behavior":     true,   // đúng expected_behavior không?
      "score_citation":     false,  // trích dẫn điều khoản đúng không?
      "retrieval_hit_rate": 0.25,   // |retrieved ∩ reference| / |reference| (0.0–1.0)
      "retrieval_hit_rate_pct": 25.0, // % hiển thị
      "retrieval_missing": ["d7_k10_b", "d7_k13_b", "d7_k13_d"],
      "retrieval_extra": [],
      "scored_at": "2026-04-01T12:00:00Z"
    }
  ],
  "total": 1
}
```

---

## 5. GET `/eval/stats/:sessionId`
Lấy thống kê tổng hợp của một eval session. Tất cả scores là tỉ lệ % (0–100), tính trên các câu đã có kết quả từ LangSmith.

### Response (200 OK)
```json
{
  "session_id": "8b5d38db-1300-47bf-af7c-500e318d1f7e",
  "total": 5,
  "scored": 5,
  "pct_correctness":  80.0,  // % câu trả lời đúng pháp lý (correctness evaluator)
  "pct_groundedness": 100.0, // % không hallucinate (groundedness evaluator)
  "pct_behavior":     100.0, // % đúng expected_behavior (behavior_compliance evaluator)
  "pct_citation":     60.0,  // % trích dẫn điều khoản đúng (citation_accuracy evaluator)
  "avg_retrieval_hit_rate": 50.0  // % node hit trung bình (retrieval_node_match, * 100)
}
```

---
