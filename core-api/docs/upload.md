# Upload API

Đường dẫn cơ sở: `/api/v1/upload`

| Endpoint | Method | Guard / Phân quyền | Role | Mô tả |
|----------|--------|---------------------|------------|-------|
| `/` | `POST` | `JWT Bearer`, `PoliciesGuard` | `USER` | Upload tối đa 2 hình ảnh đính kèm (multipart/form-data), trường `images`. Backend tối ưu RAM bằng Nodejs File Stream Pipeline và framework Sharp, resize tự động 2000px, nén WebP giữ chi tiết cạnh (`smartSubsample`), sau đó Stream thẳng qua Cloudinary API. Trả về mảng chứa `url` và `public_id`. |
| `/:publicId` | `DELETE` | `JWT Bearer`, `PoliciesGuard` | `USER` | Xóa ảnh khỏi hệ thống lưu trữ Cloudinary dựa theo `publicId` trả về ở API POST. |

## Các cấu hình Memory / Tối ưu tích hợp
- Multi-pipe Memory efficient: Hệ thống bỏ qua bước lưu trữ disk-storage hay buffer-clone, thay vào đó pipe thẳng `Express.Multer.File` Raw stream qua thuật toán Resize của **Sharp** (WebP/High-Edge detail chroma subsampling) và pipe tiếp tới REST Endpoint của **Cloudinary**.
- Khuyến kích gọi sau API này, Client mới dùng `url` để gọi tiếp `/ask/stream`.
