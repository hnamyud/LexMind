# Conversations API

Đường dẫn cơ sở: `/api/v1/conversations`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/` | `GET` | `JWT Bearer`, `CASL (Read Conversation)` | Mặc định | Lấy danh sách lịch sử các cuộc hội thoại của user hiện tại, hỗ trợ phân trang thông qua query params: `current` (trang hiện tại) và `pageSize` (số dòng chia trang). |
| `/cursor` | `GET` | `JWT Bearer` | Mặc định | Phân trang cursor theo `updatedAt DESC, id DESC`. Dùng cho sidebar/infinite scroll; không chạy `COUNT(*)` và không dùng `OFFSET`. |
| `/:id` | `PUT` | `JWT Bearer` | Mặc định | Cập nhật thông tin cuộc trò chuyện (Ví dụ: `title` hoặc `summary`). Dùng để backend hoặc user tự cập nhật tên cuộc trò chuyện. |
| `/:id` | `DELETE`| `JWT Bearer`, `CASL (Delete Conversation)` | Mặc định | Xóa (Soft-delete) một cuộc trò chuyện ra khỏi danh sách lịch sử dựa trên `id`. |

## Cursor pagination

Request trang đầu:

```http
GET /api/v1/conversations/cursor?limit=20
Authorization: Bearer <access-token>
```

Response:

```json
{
  "statusCode": 200,
  "message": "Lấy danh sách cuộc trò chuyện thành công!",
  "data": {
    "result": [
      {
        "id": "conversation-uuid",
        "title": "Quy định vượt đèn đỏ",
        "summary": null,
        "createdAt": "2026-07-13T09:00:00Z",
        "updatedAt": "2026-07-13T09:15:00Z"
      }
    ],
    "pageInfo": {
      "nextCursor": "eyJ0aW1lc3RhbXAiOiIuLi4iLCJpZCI6Ii4uLiJ9",
      "hasMore": true
    }
  }
}
```

Request trang tiếp theo:

```http
GET /api/v1/conversations/cursor?limit=20&cursor=<nextCursor>
```

- `limit`: từ `1` đến `100`, mặc định `20`.
- Cursor là opaque token; client chỉ lưu và gửi lại, không tự giải mã hoặc chỉnh sửa.
- Khi `hasMore=false`, `nextCursor=null` và không cần gọi thêm.
- Endpoint `/` cũ vẫn được giữ để tương thích frontend dùng page number.

## Ghi chú
- `Title` (tiêu đề hội thoại) có thể được tự động tạo ngầm từ `TitleGeneratorService` thông qua Event emitter khi có đoạn chat đầu tiên. User cũng có thể sửa thông qua PUT method.
- Việc xóa chỉ là "Soft-delete" (có cờ `isDeleted` trong DB). Để bảo toàn lịch sử dữ liệu đối chiếu với LLM.
- Conversation có tin nhắn mới sẽ thay đổi `updatedAt` và quay lên đầu danh sách. Frontend nên refresh trang đầu sau khi gửi tin nhắn.
