# SKILL: ĐỌC HIỂU ĐỒ THỊ PHÁP LÝ (LEGAL GRAPH COMPREHENSION)

## MÔ TẢ
Trích xuất, phân tích và hệ thống hóa thông tin pháp lý từ dữ liệu đồ thị JSON
trả về từ Neo4j, đảm bảo không bỏ sót chế tài bổ sung hoặc ngoại lệ pháp lý.

## CẤU TRÚC DỮ LIỆU ĐỒ THỊ (XML)
Dữ liệu được cung cấp dưới dạng XML với cấu trúc phả hệ: Action → Point → Clause → Article.
Mỗi node được bao trong tag `&lt;source id="..." score="..." label="..."&gt;` với nội dung trong `&lt;content&gt;` và quan hệ trong `&lt;relationships&gt;`.
Các quan hệ quan trọng cần nhận diện (thuộc tính `type` trong tag `&lt;rel&gt;`):
- `DAN_DEN_HAU_QUA`     → liên kết Action với node Consequence (mức phạt)
- `NGOAI_TRU`           → ngoại lệ, trường hợp không áp dụng
- `THAY_THE_CHO`        → văn bản/điều khoản thay thế
- `UU_TIEN_AP_DUNG`     → ưu tiên áp dụng khi có xung đột
- `DIEU_KIEN_KICH_HOAT` → điều kiện kích hoạt hành vi

## CÁCH PHÂN TÍCH
1. **Truy vết Mức phạt:** Chỉ lấy số tiền và hình thức phạt từ node
   `Consequence` liên kết qua quan hệ `DAN_DEN_HAU_QUA` với `Action`.
   Bắt buộc liệt kê đủ các hình phạt bổ sung: tước GPLX (thời hạn cụ thể),
   tạm giữ xe, tịch thu tang vật.
2. **Bảo toàn Phả hệ:** Trình bày theo thứ tự Article → Clause → Point.
3. **Xác định Ngoại lệ:** Quét quan hệ `NGOAI_TRU`. Nếu tồn tại, bắt buộc
   trình bày ở mục "Lưu ý quan trọng".

## CẤM TUYỆT ĐỐI
- Tự bịa ra mức phạt không có trong node `Consequence` của Graph.
- Bỏ qua hình phạt bổ sung (tước GPLX, tạm giữ xe).
- Dùng tên quan hệ sai (ví dụ: `HAS_CONSEQUENCE`, `EXCEPTION_IN`).