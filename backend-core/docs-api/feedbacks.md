# Feedbacks API

Đường dẫn cơ sở: `/api/v1/feedbacks`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/message/:messageId` | `POST` | `JWT Bearer` | Mặc định | Gửi phản hồi đánh giá cho tin nhắn từ AI (Like 👍 hoặc Dislike 👎). Nếu User đã có đánh giá, hệ thống sẽ thực hiện hàm upsert thành đánh giá mới. Body gửi dữ liệu `isLike` (boolean) và `reason` (Lý do chọn/tùy chọn). |
| `/message/:messageId` | `GET` | `JWT Bearer`, `CASL (Manage All)` | Mặc định | **Admin only**. Xem tất cả các đánh giá/góp ý của người dùng dành cho một tin nhắn cụ thể do AI trả lời. |

## Ghi chú
- Tính năng thiết kế chuyên biệt để đánh giá chất lượng RAG Model và LLM Responses.
- Rất hạn chế quyền read (GET) để quản trị viên mới được thao tác xem feedback, User sẽ chỉ được quyền Submit qua hàm POST (upsert logic).
