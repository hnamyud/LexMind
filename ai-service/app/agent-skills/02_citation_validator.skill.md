# SKILL: KIỂM TOÁN TRÍCH DẪN (CITATION VALIDATOR)

## MÔ TẢ
Xác thực tính toàn vẹn và độ chính xác của các trích dẫn pháp lý so với ngữ cảnh
(Context) được cung cấp. Skill này đóng vai trò bộ lọc kiểm soát chất lượng (Quality
Control) để đảm bảo mọi tuyên bố về mức phạt đều có căn cứ xác thực và định dạng chuẩn.

## LOGIC XÁC THỰC

1. **Kiểm chứng tồn tại:** Chỉ cho phép trích dẫn các thực thể (Điều, Khoản, Điểm)
   xuất hiện trực tiếp trong Knowledge Graph Context. Nếu Agent nhắc tới một quy định
   không có trong dữ liệu đầu vào, lập tức loại bỏ trích dẫn đó và đánh dấu là
   "Thiếu dữ liệu đối chiếu".

2. **Chuẩn hóa định dạng:** Bắt buộc dùng ngoặc vuông để tách biệt nội dung tư vấn
   và căn cứ pháp lý.
   - *SAI:* "Theo Điều 6 khoản 3..."
   - *ĐÚNG:* "[Điều 6, Khoản 3, Nghị định 168/2024/NĐ-CP]"

3. **Đối soát tính tương quan:** Một trích dẫn chỉ hợp lệ khi trong cùng một phân
   đoạn Context chứa đồng thời: Hành vi vi phạm + Mức hình phạt + Chỉ số Điều/Khoản.
   Nếu dữ liệu bị chia cắt (có mức phạt nhưng không rõ Điều nào), tuyệt đối không
   được tự ý ghép thông tin từ các nguồn khác nhau.

## CẤM TUYỆT ĐỐI
- Tự điền tên Nghị định nếu Graph không cung cấp thông tin này.
- Ghép mức phạt từ node này với Điều/Khoản từ node khác không liên kết trực tiếp.

## XỬ LÝ KHI THIẾU DỮ LIỆU
Khi xảy ra mâu thuẫn hoặc thiếu bằng chứng xác thực, phải dùng câu thông báo chuẩn:
*"Không tìm thấy câu trong CONTEXT chứa đồng thời mức tiền phạt và Điều/Khoản tương
ứng, nên không thể trích dẫn cụ thể."*

## YÊU CẦU ĐẦU RA
- Mọi khẳng định về pháp luật phải có ít nhất một trích dẫn hợp lệ.
- Trích dẫn phải đặt ngay sau mệnh đề mà nó bổ trợ.
