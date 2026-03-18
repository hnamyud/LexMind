# Conversations API

Đường dẫn cơ sở: `/api/v1/conversations`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/` | `GET` | `JWT Bearer`, `CASL (Read Conversation)` | Mặc định | Lấy danh sách lịch sử các cuộc hội thoại của user hiện tại, hỗ trợ phân trang thông qua query params: `current` (trang hiện tại) và `pageSize` (số dòng chia trang). |
| `/:id` | `PUT` | `JWT Bearer` | Mặc định | Cập nhật thông tin cuộc trò chuyện (Ví dụ: `title` hoặc `summary`). Dùng để backend hoặc user tự cập nhật tên cuộc trò chuyện. |
| `/:id` | `DELETE`| `JWT Bearer`, `CASL (Delete Conversation)` | Mặc định | Xóa (Soft-delete) một cuộc trò chuyện ra khỏi danh sách lịch sử dựa trên `id`. |

## Ghi chú
- `Title` (tiêu đề hội thoại) có thể được tự động tạo ngầm từ `TitleGeneratorService` thông qua Event emitter khi có đoạn chat đầu tiên. User cũng có thể sửa thông qua PUT method.
- Việc xóa chỉ là "Soft-delete" (có cờ `isDeleted` trong DB). Để bảo toàn lịch sử dữ liệu đối chiếu với LLM.
