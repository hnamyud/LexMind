# Docs API: Messages Module

Tài liệu này cung cấp chi tiết về các endpoint thuộc module `messages` của hệ thống **Chatbot Law Backend**, phục vụ việc truy xuất lịch sử tin nhắn trong các cuộc hội thoại.

**Base URL**: `http://<domain>/api/v1/messages`

> **Lưu ý chung:**
> - Tất cả các API module này đều yêu cầu đăng nhập. Bạn cần truyền header: `Authorization: Bearer <access-token>`.
> - Người dùng chỉ có quyền lấy tin nhắn thuộc về cuộc hội thoại (conversation) của chính mình.

---

## 1. Lấy danh sách tin nhắn theo cuộc hội thoại (Get Messages By Conversation ID)
- **Endpoint**: `GET /`
- **Quyền**: Yêu cầu đăng nhập.
- **Mô tả**: Tải lịch sử toàn bộ các tin nhắn (của User và AI) thuộc về một `conversationId` cụ thể. Dữ liệu trả về sẽ đi kèm với phân trang.
- **Query Parameters**:
  - `conversationId` (bắt buộc): Mã ID của cuộc trò chuyện mà bạn cần tải tin nhắn.
  - `current` (tùy chọn, mặc định `1`): Trang hiện tại.
  - `pageSize` (tùy chọn, mặc định `10`): Số lượng tin nhắn cần load trên một trang (ví dụ khi người dùng kéo (scroll) để xem lịch sử cũ).
- **Ví dụ gọi**: `GET /api/v1/messages?conversationId=123e4567-e89b-12d3...&current=1&pageSize=20`
- **Response**: 
  - Trả về danh sách tin nhắn được sắp xếp.
  - Bao gồm `message: "Lấy danh sách tin nhắn thành công!"`.