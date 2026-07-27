# Messages API

Đường dẫn cơ sở: `/api/v1/messages`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/` | `GET` | `JWT Bearer` | Mặc định | Truy xuất toàn bộ tin nhắn thuộc một cuộc hội thoại cụ thể. Yêu cầu truyền qua Query Param: `conversationId`. Có phân trang bởi `current` và `pageSize`. |
| `/cursor` | `GET` | `JWT Bearer` | Mặc định | Tải dần tin nhắn cũ theo `createdAt DESC, id DESC`; không chạy `COUNT(*)` hoặc dùng `OFFSET`. |

## Cursor pagination

Request trang đầu (các tin nhắn mới nhất):

```http
GET /api/v1/messages/cursor?conversationId=<uuid>&limit=30
Authorization: Bearer <access-token>
```

Response:

```json
{
  "statusCode": 200,
  "message": "Lấy danh sách tin nhắn thành công!",
  "data": {
    "result": [
      {
        "id": "message-uuid",
        "sender": "bot",
        "content": "...",
        "thought": null,
        "metadata": {},
        "createdAt": "2026-07-13T09:15:00Z"
      }
    ],
    "pageInfo": {
      "nextCursor": "eyJ0aW1lc3RhbXAiOiIuLi4iLCJpZCI6Ii4uLiJ9",
      "hasMore": true
    }
  }
}
```

Request tải các tin nhắn cũ hơn:

```http
GET /api/v1/messages/cursor?conversationId=<uuid>&limit=30&cursor=<nextCursor>
```

- `limit`: từ `1` đến `100`, mặc định `30`.
- Kết quả được trả mới nhất trước (`DESC`). Frontend có thể đảo mảng trước khi chèn lên đầu khung chat.
- Cursor là opaque token; cursor sai định dạng trả `400`.
- Quyền sở hữu conversation vẫn được kiểm tra trước khi trả messages.
- Endpoint `/` cũ vẫn hoạt động với `current` và `pageSize`.

## Ghi chú
- Lịch sử tin nhắn sẽ bao gồm thông tin chi tiết:
  - `sender` (user / bot)
  - `content` (nội dung hiển thị)
  - `thought` (quá trình suy luận tư duy của AI trước khi ra quyết định)
  - `metadata` (chứa các citations/nguồn links web trích dẫn của kết quả)
- Hệ thống hỗ trợ lazy-loading (phân trang) trên Frontend cho độ trễ tin nhắn tối ưu.
- Cursor sử dụng đồng thời `createdAt` và `id`, tránh bỏ sót khi nhiều message có cùng timestamp.
