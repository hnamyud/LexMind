# Messages API

Đường dẫn cơ sở: `/api/v1/messages`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/` | `GET` | `JWT Bearer` | Mặc định | Truy xuất toàn bộ tin nhắn thuộc một cuộc hội thoại cụ thể. Yêu cầu truyền qua Query Param: `conversationId`. Có phân trang bởi `current` và `pageSize`. |

## Ghi chú
- Lịch sử tin nhắn sẽ bao gồm thông tin chi tiết:
  - `sender` (user / bot)
  - `content` (nội dung hiển thị)
  - `thought` (quá trình suy luận tư duy của AI trước khi ra quyết định)
  - `metadata` (chứa các citations/nguồn links web trích dẫn của kết quả)
- Hệ thống hỗ trợ lazy-loading (phân trang) trên Frontend cho độ trễ tin nhắn tối ưu.
