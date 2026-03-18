# Docs API: Conversations Module

Tài liệu này cung cấp chi tiết về các endpoint thuộc module `conversations` của hệ thống **Chatbot Law Backend**, phục vụ việc quản lý danh sách cuộc hội thoại của người dùng.

**Base URL**: `http://<domain>/api/v1/conversations`

> **Lưu ý chung:**
> - Tất cả các API module này đều yêu cầu đăng nhập. Bạn cần truyền header: `Authorization: Bearer <access-token>`.
> - Các request sẽ được check policy (quyền hạn đọc, xóa cuộc trò chuyện thông qua CASL). Người dùng chỉ thao tác được với các cuộc hội thoại do chính mình tạo ra.

---

## 1. Lấy danh sách cuộc trò chuyện (Get All Conversations)
- **Endpoint**: `GET /`
- **Quyền**: Yêu cầu đăng nhập, có quyền Đọc (Read - Conversation).
- **Mô tả**: Lấy danh sách tất cả các cuộc hội thoại của người dùng đang đăng nhập có phân trang (pagination). Xếp theo thời gian mới nhất.
- **Query Parameters**:
  - `current` (tùy chọn, mặc định `1`): Trang hiện tại.
  - `pageSize` (tùy chọn, mặc định `10`): Số lượng phiên hội thoại trả về trên mỗi trang.
- **Ví dụ gọi**: `GET /api/v1/conversations?current=1&pageSize=10`
- **Response**: Trả về danh sách thông tin cơ bản của các cuộc hội thoại và tổng số trang.

## 2. Cập nhật thông tin cuộc trò chuyện (Update Conversation)
- **Endpoint**: `PUT /:id`
- **Quyền**: Yêu cầu đăng nhập.
- **Mô tả**: Cập nhật lại tiêu đề (title) hoặc phần tóm tắt (summary) cho một cuộc hội thoại cụ thể.
- **Tham số URL**: 
  - `id`: Mã ID của cuộc hội thoại cần cập nhật.
- **Request Body** (JSON):
  ```json
  {
    "title": "Hỏi về mức phạt lỗi quá tốc độ",
    "summary": "Tóm tắt cuộc trò chuyện..."
  }
  ```
  *Ràng buộc dữ liệu:*
  - `title` (bắt buộc): Chuỗi, không được để trống.
  - `summary` (tùy chọn): Chuỗi.
- **Response**: `message: "Cập nhật thông tin cuộc trò chuyện thành công!"` kèm theo thông tin bản ghi vừa được update.

## 3. Xóa cuộc trò chuyện (Delete Conversation)
- **Endpoint**: `DELETE /:id`
- **Quyền**: Yêu cầu đăng nhập, có quyền Xóa (Delete - Conversation).
- **Mô tả**: Thực hiện xóa mềm (soft delete) cuộc trò chuyện. Cuộc trò chuyện sẽ biến mất khỏi danh sách nhưng vẫn lưu trong cơ sở dữ liệu để audit nếu cần.
- **Tham số URL**: 
  - `id`: Mã ID của cuộc trò chuyện cần xóa.
- **Response**: 
  ```json
  {
    "message": "Xóa cuộc trò chuyện thành công!"
  }
  ```