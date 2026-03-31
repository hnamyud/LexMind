# Kế Hoạch Tích Hợp Đa Nền Tảng Luật Mới & Cũ
*Tài liệu hướng dẫn nâng cấp hệ thống Chatbot-law khi tích hợp nhiều bộ luật, nghị định (Luật Giao thông 2024, Luật xử lý vi phạm hành chính, Nghị định 100/2019, 123/2021, 168/2024...)*

---

## 1. Cải tiến Cấu trúc Neo4j (Graph Database)

Dựa trên việc bạn đã chủ động thêm `alias` (ví dụ: `nd168_2024_dieu_...`), đây là một pattern cực kỳ đúng đắn trong hệ thống Knowledge Graph RAG. Để scale lên nhiều bộ luật, cần đồng bộ hóa cấu trúc sau:

### 1.1. Thêm thuộc tính tiêu chuẩn cho Entity
Tất cả các node (`Article`, `Action`, `Penalty`,...) cần bổ sung các properties bắt buộc:
- `law_id`: Mã văn bản (VD: `luat_gt_2024`, `nd_100_2019`, `luat_xlvphc`).
- `effective_date`: Ngày có hiệu lực (Timestamp hoặc yyyy-mm-dd).
- `status`: Trạng thái hiệu lực (`"active"`, `"expired"`, `"draft"`).

### 1.2. Mở rộng Relationship giữa các bộ luật
Luật mới thường thay thế/sửa đổi luật cũ, cần thêm các edge (relationship) sau để AI agent hiểu được ngữ cảnh thời gian:
- `(Luat_Moi)-[:THAY_THE_CHO]->(Luat_Cu)`
- `(Luat_Moi)-[:SUA_DOI_BOSUNG_CHO]->(Luat_Cu)`
- `(DieuKhoan_Moi)-[:CAP_NHAT_MUC_PHAT]->(DieuKhoan_Cu)`

**Lợi ích:** Khi user hỏi thông tin theo nghị định cũ, Graph sẽ tự động nhảy (traverse) sang nghị định mới qua relationship `[:THAY_THE_CHO]` và nhắc nhở user.

---

## 2. Nâng cấp AI Service (RAG & Truy vấn)

### 2.1. Cập nhật Pipeline Retrieve (graph_retrieval.py)
Cần nâng cấp các câu lệnh **Cypher** trong Graph Retrieval Tool để có tính "Time-Aware" (nhận thức thời gian):
- **Ưu tiên văn bản hiện hành (`status = "active"`)**: Default filter loại bỏ các luật cũ nếu user không chỉ định rõ.
- VD thay đổi Cypher:
  ```cypher
  MATCH (n)-[r]-(m)
  WHERE n.status = "active" OR n.law_id = $requested_law_id
  RETURN n
  ```

### 2.2. Xử lý logic lọc bộ luật (Router/Keyword Extraction)
- Thêm module phân tích Intent: Extract Regex để xem user có đang hỏi bộ luật cụ thể nào không (VD user nhắc "nghị định 100", AI tự extract biến `law_id = nd_100_2019`).
- Load vector search có metadata filter theo namespace hoặc `law_id`.

### 2.3. Cải tiến prompt của model (Prompt Engineering)
Cập nhật file yaml trong thư mục `prompts/`:
- Bổ sung chỉ thị: *"Nếu hệ thống truy xuất được thông tin từ nhiều bộ luật khác nhau cho cùng một hành vi (VD: NĐ 100 và Luật GT 2024), hãy dựa vào ngày hiệu lực hoặc trạng thái 'active' để cung cấp mức phạt mới nhất, đồng thời note nhỏ rằng luật cũ đã bị thay thế."*

---

## 3. Quản lý Cache & Metadata (Semantic Cache)

API Router hiện tại đã có endpoint `DELETE /cache/invalidate/{law_tag}`. Khi ingest data của luật mới (vd: `luat_gt_2024`):
1. Import data vào Neo4j với alias mới.
2. Gọi API Invalidate theo từng document để xóa các câu hỏi cũ đã bị lỗi thời:
   `DELETE /cache/invalidate/nd168_2024`
   `DELETE /cache/invalidate/luat_gt_2024`
3. Điều này ngăn AI trả về đáp án lấy từ Cache cũ chứa mức phạt chưa cập nhật.

---

## 4. Admin Dashboard / Data Pipeline

- Cần 1 module/script import dữ liệu chuẩn hóa dạng JSON/CSV. Do đã có format `alias` mới, script import cần mapping đúng `alias` này thành `ID` chính của Node trong Neo4j.
- Phải có tính năng để Admin "Mark as Expired" (Chuyển trạng thái hết hiệu lực) cho toàn bộ các node thuộc một `law_id` nhất định chỉ bằng một cú click.

---

## 5. Hiển thị UI / UX (Frontend & Output Formulation)

Khi tổng hợp câu trả lời, RAG Service nên trả về metadata của source data để gửi xuống Frontend.
- **Backend API**: Trong Array list `citations` của Node Backend, trả kèm thông tin `law_id` hoặc tên bộ luật.
- **Frontend Chat**: Tại Source Citation dưới mỗi tin nhắn Bot, hiển thị nhãn (Badge). Ví dụ: `[Luật GTĐB 2024]`, `[Điều 5 - NĐ 100]`. Đổi màu đỏ cho luật đã hết hạn, màu xanh lá cho luật đang hiện hành.

### Các công việc Actionable Tiếp Theo (To-Do List)
1. [ ] Viết lại script Neo4j Data Ingestion để tự động parse custom alias như biến `law_id`.
2. [ ] Thêm Cypher migration tạo Index/Constraint trên field `law_id` và `status` cho Neo4j để tăng tốc độ.
3. [ ] Cập nhật module RAG Prompt để AI so sánh giữa kết quả của luật cũ/mới nếu context lỡ fetch dính cả hai.
4. [ ] Viết bộ test-case mới trong `test_patterns_simple.py` với câu hỏi dạng: "Theo NĐ 100 thì abc, nhưng luật 2024 thì sao?".