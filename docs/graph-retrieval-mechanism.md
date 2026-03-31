# Cơ Chế Graph Retrieval (Tra cứu Đồ thị) trong AI Service

*Tài liệu này mô tả chi tiết cơ chế hoạt động của `GraphRetrievalTool` (nằm trong `ai-service/app/tools/graph_retrieval.py`). Đây là trái tim của hệ thống RAG (Retrieval-Augmented Generation) pháp lý, chịu trách nhiệm tìm kiếm các điều luật và mức phạt phù hợp nhất với câu hỏi của người dùng.*

---

## 1. Tổng quan Kiến trúc

Cơ chế tra cứu được thiết kế theo mô hình **Parallel 4-Prong Strategy** (4 luồng song song) kết hợp **RRF (Reciprocal Rank Fusion)** và các thuật toán chấm điểm hậu xử lý (Post-processing Boosting).

Mục tiêu thiết kế:
- **Tốc độ cao**: 4 luồng chạy bất đồng bộ (`asyncio.gather`), được bảo vệ bởi timeout riêng (`timeout guards`).
- **Độ chính xác RAG**: Dung hòa giữa *tìm kiếm từ khóa truyền thống* và *tìm kiếm ngữ nghĩa vector*, kết hợp duyệt quan hệ thực tế trong luật.
- **Tối ưu theo nghiệp vụ đặc thù**: Hỗ trợ 2 case khó của miền Luật (Câu hỏi ngược từ kết quả phạt & Phân loại phương tiện).

---

## 2. Bốn Luồng Truy Xuất Song Song (4-Prong Strategy)

### Nhánh 1: Vector Search (Ngữ Nghĩa)
- **Cách hoạt động**: Lấy vector nhúng (embedding) của câu hỏi $\rightarrow$ Sử dụng k-NN (Cosine Similarity) trên vector index của Neo4j.
- **Ưu điểm**: Hiểu được ý định khi người dùng dùng từ lóng, dùng sai từ pháp lý (vd: "lấn làn" $\rightarrow$ "đi không đúng phần đường").
- **Hạn chế**: Khi luật có quá nhiều keyword giống nhau (vd: "ô tô vượt đèn đỏ" và "xe máy vượt đèn đỏ"), vector search có thể trả về nhầm phương tiện.

### Nhánh 2: Keyword Search (Truy vấn Fulltext Index bằng Lucene)
- **Cách hoạt động**: Sử dụng Fulltext Index thay vì `CONTAINS` truyền thống (giảm độ phức tạp từ $O(n)$ xuống $O(\log n)$).
- **Ưu điểm**: Bắt cực kỳ chuẩn xác các từ khóa cụ thể như "0,25 miligam", "nồng độ cồn", "2.000.000 đồng". Tìm đích danh số hiệu.
- **Cypher Mẫu**: `CALL db.index.fulltext.queryNodes("entity_text_index", $keyword)...`

### Nhánh 3: Graph Traversal (Duyệt Đồ Thị Thực Thể)
- **Cách hoạt động**: Chạy thuật toán tìm theo ngữ cảnh của các **Entities** (được Router bóc tách sẵn như `violation`, `vehicle_type`).
- **Ưu điểm**: Đi dọc theo Map quan hệ: `(Action) -[:AP_DUNG_CHO]-> (Vehicle)`, từ đó khoanh vùng nhỏ nhất.

### Nhánh 4: Consequence-First Lookup (Tra Cứu Ngược Từ Hậu Quả)
*(Được phát triển qua tính năng Intelligence Upgrades)*
- **Cách hoạt động**: 
  1. Phân tích RegEx phát hiện câu hỏi thuộc về "mức phạt" (vd: *phạt 5 triệu*, *tước bằng 3 tháng*, *trừ 4 điểm*).
  2. Map số tiền phạt/thời gian phạt thành chuỗi chuẩn (`_extract_consequence_keyword`).
  3. Tìm kiếm **node Consequence** (Mức phạt) trước.
  4. Traverse **NGƯỢC** qua relationship `[:DAN_DEN_HAU_QUA]` để tìm trả về **Action** (Hành vi).
- **Ưu điểm**: Hỗ trợ các câu hỏi tra ngược như: *"Phạt 2 đến 3 triệu là lỗi gì?"*. Vector search thường "chào thua" các câu dạng này.

---

## 3. Thuật Toán Gộp Kết Quả - RRF (Reciprocal Rank Fusion)

Do mỗi nhánh trả về hệ thống xếp hạng điểm (score) bằng thang đo khác nhau (Ví dụ: Cosine Similarity từ 0.0 - 1.0, nhưng Fulltext score từ 0 - vô cực). **RRF** được dùng để gộp không cần quan tâm thang độ.

$$ \text{RRF\_Score}(n) = \sum_{sys} \frac{1}{k + \text{Rank}_{sys}(n)} $$
*(Trong đó $k=60$ theo thông lệ)*

- Tất cả kết quả từ 4 luồng đổ về list duy nhất. Node nào xuất hiện liên tiếp top đầu của cả 4 luồng sẽ đứng vị trí số 1.
- Hệ thống áp dụng **RRF Threshold** để lọc bỏ các kết quả nhiễu ở đuôi.

---

## 4. Hậu Xử Lý: Vehicle-Aware Boosting (Nâng Điểm Theo Phương Tiện)

Sau khi có RRF Score, thuật toán hậu xử lý kích hoạt để xử lý bài toán **"Bị nhầm phương tiện"**:
1. Tool đọc biến `vehicle_type` extract được từ câu hỏi (vd: `xe máy`). Cân bằng loại xe thông qua map `VEHICLE_ALIASES`.
2. Duyệt qua mảng kết quả, kiểm tra mối quan hệ `[:AP_DUNG_CHO]` của từng Action.
3. Nếu Node có nhánh link tới đúng loại phương tiện $\rightarrow$ **Nhân điểm (Boost Multiplier: x1.3)**.
4. Sắp xếp `(re-sort)` lại list kết quả RRF.

*Tác động*: Đẩy chắc chắn các mức xử phạt của "xe máy" lên đứng trước kết quả "ô tô" khi user hỏi về xe máy.

---

## 5. Tham Số Cấu Hình (Configuration Fields)

Công cụ khi khởi tạo nhận vào các Parameter tùy chỉnh quan trọng sau:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `keyword_timeout` | float | 3.0s | Giới hạn thời gian kết nối của Fulltext search. |
| `vector_timeout` | float | 5.0s | Giới hạn thời gian vector embedding search. |
| `graph_timeout` | float | 5.0s | Giới hạn thời gian tra cứu cấu trúc Entity. |
| `consequence_timeout`| float| 3.0s | Giới hạn thời gian truy vấn ngược Node phạt. |
| `vehicle_boost_enabled`| bool | True | Bật/tắt Module ưu tiên phương tiện.|
| `vehicle_boost_multiplier`| float | 1.3 | Hệ số x RRF_Score nếu tìm đúng xe. |

## 6. Output (Dữ Liệu Đầu Ra Cho LLM)
Kết quả sẽ được convert thành string tổng hợp có cấu trúc Markdown, bao gồm đầy đủ: Tên lỗi, Mô tả chi tiết, Xe áp dụng, Mức Phạt, Số điểm trừ, Thời gian tước giấy phép và Text nguồn của Điều/Khoản luật. LLM Synthesis sau đó sẽ nhận Context này và trả lời tự nhiên lại cho user.