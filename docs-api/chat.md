# Docs API: Chat Module

Tài liệu này cung cấp chi tiết về các endpoint thuộc module `chat` của hệ thống **Chatbot Law Backend**, chuyên trách về việc giao tiếp trực tiếp với AI theo cơ chế real-time stream.

**Base URL**: `http://<domain>/api/v1/chat`

> **Lưu ý chung:**
> - Tất cả các API module này đều yêu cầu đăng nhập. Bạn cần truyền header: `Authorization: Bearer <access-token>`.
> - Module chat có áp dụng throttling (giới hạn số request) để chống spam (ví dụ 5 request / 1 phút).

---

## 1. Hỏi AI (Ask AI Stream)
- **Endpoint**: `POST /ask/stream`
- **Quyền**: Yêu cầu đăng nhập. Có kiểm tra quyền sở hữu cuộc hội thoại (Conversation Owner).
- **Mô tả**: Gửi một câu hỏi đến AI và sẽ nhận lại luồng (stream) nội dung câu trả lời. Điều này cho phép phía Frontend có thể hiển thị từng chữ theo thời gian thực giống ChatGPT.
- **Request Body** (JSON):
  ```json
  {
    "question": "Vượt đèn đỏ bị phạt bao nhiêu tiền?",
    "conversationId": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```
  *Ràng buộc dữ liệu:*
  - `question` (bắt buộc): Chuỗi, tối thiểu 10 ký tự, tối đa 1000 ký tự.
  - `conversationId` (tùy chọn): Định danh của cuộc hội thoại nếu bạn muốn tiếp tục ngữ cảnh cũ. Nếu không truyền, hệ thống sẽ tự động tạo một phiên chat (conversation) mới.
- **Response**: Trả về dữ liệu kiểu dạng stream text. Frontend cần cấu hình fetch hoặc axios để hứng dữ liệu luồng (stream chunk).

---

## 2. Tạo Lại Câu Trả Lời (Regenerate Answer)
- **Endpoint**: `POST /regenerate/:messageId`
- **Quyền**: Yêu cầu đăng nhập.
- **Mô tả**: Dùng để tính toán lại / sinh lại câu trả lời cho một tin nhắn nhất định trước đó (do AI trả lời lỗi hoặc bạn muốn đáp án mới). Endpoint này cũng sẽ trả về dữ liệu bằng stream như API hỏi AI gốc.
- **Tham số trên URL**:
  - `messageId` (bắt buộc): ID của tin nhắn cụ thể mà người dùng muốn AI trả lời lại.
- **Response**: Trả về dữ liệu dạng stream text. Tương tự như `/ask/stream`.