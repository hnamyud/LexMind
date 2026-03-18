# Docs API: Authentication Module

Tài liệu này cung cấp chi tiết về các endpoint thuộc module `auth` của hệ thống **Chatbot Law Backend**, nhằm giúp Frontend dễ dàng tích hợp.

**Base URL**: `http://<domain>/api/v1/auth`

---

## 1. Đăng nhập (Local Login)
- **Endpoint**: `POST /login`
- **Quyền**: Public
- **Mô tả**: Sử dụng email và mật khẩu để xác thực và nhận JWT Token.
- **Request Body** (JSON):
  ```json
  {
    "email": "user@example.com",
    "password": "password123"
  }
  ```
  *Lưu ý*: Mật khẩu phải có ít nhất 8 ký tự.
- **Response**: Thành công trả về thông tin đăng nhập (như accessToken, refreshToken và thông tin user tùy thuộc vào service).

## 2. Đăng ký (Register)
- **Endpoint**: `POST /register`
- **Quyền**: Public
- **Mô tả**: Tạo tài khoản người dùng mới.
- **Request Body** (JSON):
  ```json
  {
    "name": "Nguyen Van A",
    "email": "user@example.com",
    "password": "password123"
  }
  ```
- **Response**: Trả về `message: "Đăng ký thành công!"` kèm theo dữ liệu user đã được tạo.

## 3. Lấy thông tin tài khoản (Get Profile)
- **Endpoint**: `GET /profile`
- **Quyền**: Yêu cầu Header `Authorization: Bearer <access-token>`.
- **Mô tả**: Lấy thông tin chi tiết của người dùng đang đăng nhập (Yêu cầu qua check policy quyền đọc User).
- **Response**: Trả về thông tin user và `message: "Lấy thông tin user thành công!"`.

## 4. Đăng xuất (Logout)
- **Endpoint**: `POST /logout`
- **Quyền**: Yêu cầu Header `Authorization: Bearer <access-token>`.
- **Mô tả**: Xóa phiên đăng nhập (clear refresh token hoặc clear cookie tùy implement).
- **Response Body**:
  ```json
  {
    "message": "Đăng xuất thành công!"
  }
  ```

## 5. Đăng nhập bằng Google (Google OAuth)
- **Bắt đầu Flow (Frontend Gọi)**: `GET /google/login`
  - *Mô tả*: Frontend có thể gắn thẻ `<a>` hoặc redirect trình duyệt đến URL này để người dùng chọn tài khoản Google.
- **Callback (Chỉ dành cho Backend/Xử lý Redirect)**: `GET /google/callback`
  - *Mô tả*: Trả về từ Google OAuth. Backend sẽ kiểm tra, tạo user và redirect trình duyệt về FE domain (kèm theo token trên đường dẫn url gốc).

## 6. Xác thực OTP (Verify OTP)
- **Endpoint**: `POST /verify-otp`
- **Quyền**: Public (chống spam định dạng 3 lần / 1 phút)
- **Mô tả**: Dùng để kiểm tra xem mã OTP được gửi tới email (ví dụ trong quy trình quên mật khẩu) có chính xác hay không.
- **Request Body** (JSON):
  ```json
  {
    "email": "user@example.com",
    "otp": "123456"
  }
  ```
  *Lưu ý*: OTP phải là chuỗi số có đúng 6 ký tự.
- **Response Body**:
  ```json
  {
    "message": "Xác thực OTP thành công!"
  }
  ```

## 7. Đặt lại mật khẩu mới (Reset Password - Quên Mật Khẩu)
- **Endpoint**: `POST /reset-password`
- **Quyền**: Public (chống spam định dạng 3 lần / 1 phút)
- **Mô tả**: Submit lại mật khẩu mới cùng với mã OTP.
- **Request Body** (JSON):
  ```json
  {
    "email": "user@example.com",
    "otp": "123456",
    "newPassword": "newpassword123"
  }
  ```
  *Lưu ý*: Mật khẩu phải có ít nhất 8 ký tự.
- **Response Trả Về**: `message: "Đặt lại mật khẩu thành công!"`

## 8. Thay đổi mật khẩu khi đã đăng nhập (Change Password)
- **Endpoint**: `POST /change-password`
- **Quyền**: Yêu cầu Header `Authorization: Bearer <access-token>`.
- **Mô tả**: Cho phép user đổi mật khẩu khi đang đăng nhập.
- **Request Body** (JSON):
  ```json
  {
    "oldPassword": "oldpassword123",
    "newPassword": "newpassword123",
    "confirmPassword": "newpassword123"
  }
  ```
  *Lưu ý*: Mật khẩu mới phải có ít nhất 6 ký tự.
- **Response Trả Về**: `message: "Thay đổi mật khẩu thành công!"`

## 9. Làm mới token (Refresh Token)
- **Endpoint**: `GET /refresh`
- **Quyền**: Public (yêu cầu file cookie `refresh_token` từ request)
- **Mô tả**: Sử dụng refreshToken được cấp trước đó (lưu ở Cookie hoặc được gửi kèm request) để cấp lại một accessToken mới khi phiên làm việc cũ hết hạn mà người dùng không cần đăng nhập lại.
- **Cookies Yêu Cầu**: `refresh_token=<token>` (Bắt buộc phải kèm cookies khi gọi, frontend phải set `withCredentials: true` khi gọi axios/fetch).
- **Response**: Trả về `accessToken` mới kèm thông tin của người dùng và thiết lập lại `refresh_token` vào Cookie. `message: "Làm mới token thành công!"`

---
*Lưu ý chung cho Frontend*: 
- Các response hiện tại sử dụng một Interceptor `TransformInterceptor`, các kết quả sẽ thường bọc bên trong một wrapper có format `{ statusCode, message, data }`.
- Các route có yêu cầu xác thực (`@ApiBearerAuth('access-token')`) đều phải mang token nhận được từ lúc login gán vào header Authorization dưới format: `Bearer <token>`.
