# Chat API

Đường dẫn cơ sở: `/api/v1/chat`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/ask/stream` | `POST` | `JWT Bearer`, `<ConversationOwnerGuard>` | 5 req / 60s | Gửi câu hỏi cho AI và nhận câu trả lời dạng Server-Sent Events (SSE). Body yêu cầu `question` và `conversationId`. Hỗ trợ đính kèm `image` (URL, public_id từ Cloudinary). |
| `/regenerate/:messageId` | `POST` | `JWT Bearer` | 5 req / 60s | Yêu cầu AI tạo lại (regenerate) câu trả lời cho một tin nhắn lỗi. Cần truyền vào tham số param `messageId`. Tự động nhận diện lại Image của câu hỏi cũ nếu có để feed cho Model. |
| `/law-detail/:nodeId` | `GET` | `JWT Bearer` | 30 req / 60s | Lấy chi tiết thông tin luật giao thông trực tiếp từ Neo4j Knowledge Graph thông qua ID của node (điều/khoản). |

## Ghi chú
- API `/ask/stream` được phân luồng xử lý chặt chẽ. Backend sẽ Proxy stream dạng NDJSON từ FastAPI (AI service) biến đổi thành chuẩn SSE đến Frontend Client để render typing effect realtime.
- Hỗ trợ Image Pipeline thông qua body `image: { url, public_id }` và tự động mapping metadata cho RAG Vision context bên nhánh AI-Service.
- Có giới hạn hạn mức Rate limit khắt khe (5 requests mỗi 60 giây) cho các hành động cần gọi LLM (ask/trả lời) để kiểm soát tài nguyên hệ thống.
