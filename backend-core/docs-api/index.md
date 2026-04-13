# Bảng thống kê thư mục chức năng API

Đây là file tổng hợp tra cứu toàn bộ Endpoints của Backend NestJS:

- [App / General API](./app.md): Các API dùng chung mức hệ thống (vd: Graph Demo).
- [Authentication API](./auth.md): Quản lý đăng nhập, JWT, OAuth Google, OTP.
- [Chat API](./chat.md): Quản lý luồng giao tiếp Streaming với LLM (FastAPI), tái tạo câu trả lời, lấy chi tiết luật trong Knowledge Graph.
- [Conversations API](./conversations.md): Quản lý lịch sử phòng trò chuyện.
- [Messages API](./messages.md): Truy xuất các dòng thời gian / lịch sử tin nhắn và context hội thoại.
- [Feedbacks API](./feedbacks.md): Hệ thống chấm điểm đánh giá phản hồi để theo dõi chất lượng RAG.
- [Upload API](./upload.md): Xử lý tải ảnh, stream qua Sharp nén WebP và đẩy thẳng lên Cloudinary.
- [Admin API](./admin.md): Giám sát hệ thống, quản lý người dùng, hội thoại và theo dõi hiệu suất/chất lượng AI (Phase 3).

*(Module Users hiện đại diện cho Service quản lý nội bộ trên NestJS, chưa có API endpoint phơi bày ra ngoài).*
