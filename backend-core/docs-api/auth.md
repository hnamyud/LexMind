# Authentication API

Đường dẫn cơ sở: `/api/v1/auth`

| Endpoint | Method | Guard / Phân quyền | Rate Limit | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/login` | `POST` | `@Public`, `<LocalAuthGuard>` | Mặc định | Đăng nhập hệ thống. Yêu cầu Body chứa `email` và `password`. |
| `/logout` | `POST` | `JWT Bearer` | Mặc định | Đăng xuất người dùng hiện tại. |
| `/register` | `POST` | `@Public` | Mặc định | Đăng ký tài khoản mới. |
| `/google/login` | `GET` | `@Public`, `<GoogleAuthGuard>` | Mặc định | Redirect người dùng sang trang đăng nhập Google. |
| `/google/callback` | `GET` | `@Public`, `<GoogleAuthGuard>` | Mặc định | Xử lý callback từ Google và tự động chuyển hướng về Frontend (`BROWSER_REDIRECT_URI`) mang theo Access Token. |
| `/profile` | `GET` | `JWT Bearer`, `CASL (Read User)` | Mặc định | Lấy thông tin tài khoản người dùng đang đăng nhập. |
| `/refresh` | `GET` | `@Public` | Mặc định | Làm mới `access_token` tự động thông qua `refresh_token` lưu trong HttpOnly Cookie. |
| `/verify-otp` | `POST` | `@Public` | 3 req / 60s | Xác minh OTP hỗ trợ quên mật khẩu. Yêu cầu Body `email` và `otp`. |
| `/reset-password` | `POST` | `@Public` | 3 req / 60s | Đặt lại mật khẩu mới sau khi xác minh OTP. |
| `/change-password` | `POST` | `JWT Bearer` | Mặc định | Cho phép người dùng đang đăng nhập đổi mật khẩu hiện tại. |

## Luồng Auth chính
- Hệ thống hỗ trợ Local Auth (Email/Pass) và Google OAuth.
- JWT Access Token được cấp trực tiếp. Refresh Token được lưu an toàn trong httpOnly Cookie để sử dụng ở endpoint `/refresh`.
