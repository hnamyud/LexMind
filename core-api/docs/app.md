# App / General API

Các API dùng chung cho toàn hệ thống, hiện được đặt ở `AppController`.

## 1. Lấy dữ liệu Graph Demo (Frontend Use)
- **Endpoint:** `GET /graph/demo` *(Lưu ý: Nếu hệ thống bật versioning thì sẽ là `/api/v1/graph/demo`)*
- **Mô tả:** Truy vấn đồ thị thật từ FastAPI/Neo4j bằng seed node `id`, chạy theo mẫu:
  `MATCH path = (d:Entity {id: $node_id})-[*1..2]-(n) RETURN path`.
  Kết quả trả về là subgraph (nodes + edges) để frontend render Graph UI.
- **Yêu cầu xác thực:** Không (public endpoint).
- **Rate Limit:** 30 request / phút.

### Query Parameters
- `id` *(optional, string)*: ID node gốc dùng làm seed để truy vấn path 1..2 hops.
- **Mặc định:** `nd168_2024_d7_k7_c`.

### Node ID Format (Mới)

Hệ thống đã chuyển sang format ID mới với tiền tố `{doc_ref}_`:

**Format:** `{doc_ref}_{structure}`

**Document References:**
- `nd168_2024`: Nghị định 168/2024/NĐ-CP
- `l35_2024`: Luật Đường bộ 2024
- `l36_2024`: Luật Trật tự, An toàn giao thông đường bộ 2024

**Structure Patterns:**
- Chỉ điều: `{doc_ref}_dieu_{N}`
  - Ví dụ: `l35_2024_dieu_13`, `nd168_2024_dieu_7`
- Điều + khoản: `{doc_ref}_d{N}_k{N}`
  - Ví dụ: `nd168_2024_d7_k7`, `l35_2024_d13_k1`
- Điều + khoản + điểm: `{doc_ref}_d{N}_k{N}_{letter}`
  - Ví dụ: `nd168_2024_d7_k7_c`, `l35_2024_d13_k1_a`

**Backward Compatibility:**
- Format cũ (không có tiền tố) vẫn được hỗ trợ: `d7_k7_c`, `dieu_7`
- Khuyến nghị sử dụng format mới cho tất cả queries

### Ví dụ gọi API
- `GET /graph/demo`
- `GET /graph/demo?id=nd168_2024_d7_k7_c`
- `GET /api/v1/graph/demo?id=l35_2024_dieu_13`
- `GET /api/v1/graph/demo?id=nd168_2024_d18_k8_a`

### Cấu trúc Response
Trả về cấu trúc chuẩn để trực quan hoá biểu đồ mạng (Network Graph). Số lượng node/cạnh là động theo `id`.

```json
{
  "statusCode": 200,
  "message": "Get Graph Demo Data",
  "data": {
    "status": "success",
    "seed_id": "d7_k7_c",
    "query": "MATCH path = (d:Entity {id: $node_id})-[*1..2]-(n) RETURN path",
    "total_nodes": 43,
    "total_edges": 47,
    "type_meta": {
      "HanhVi": {
        "color": "#ef4444",
        "icon": "⚠️"
      },
      "PhuongTien": {
        "color": "#3b82f6",
        "icon": "🚗"
      },
      "MucPhat": {
        "color": "#f97316",
        "icon": "💰"
      },
      "HinhPhatBoSung": {
        "color": "#a855f7",
        "icon": "📋"
      },
      "VanBanPhapLy": {
        "color": "#10b981",
        "icon": "📜"
      },
      "DieuKhoan": {
        "color": "#06b6d4",
        "icon": "§"
      },
      "Entity": {
        "color": "#64748b",
        "icon": "●"
      }
    },
    "nodes": [
      {
        "id": "d7_k7_c",
        "label": "Điểm c - Không chấp hành đèn tín hiệu",
        "type": "Entity",
        "description": "c) Không chấp hành hiệu lệnh của đèn tín hiệu giao thông;"
      },
      {
        "id": "vuot_den_do",
        "label": "Không chấp hành đèn tín hiệu",
        "type": "Entity",
        "description": "Không chấp hành hiệu lệnh của đèn tín hiệu giao thông"
      },
      {
        "id": "hq_phat_4000_6000",
        "label": "Phạt tiền 4.000.000đ - 6.000.000đ",
        "type": "Entity",
        "description": "Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng"
      },
      {
        "id": "nguoi_dieu_khien_xe_mo_to",
        "label": "Người điều khiển xe mô tô, xe gắn máy",
        "type": "Entity",
        "description": "người điều khiển xe mô tô, xe gắn máy"
      },
      {
        "id": "d7_k7",
        "label": "Khoản 7 - Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng",
        "type": "Entity",
        "description": "7. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với người điều khiển xe thực hiện một trong các hành vi vi phạm sau đây:"
      },
      {
        "id": "dieu_7",
        "label": "Xử phạt người điều khiển xe mô tô, xe gắn máy vi phạm quy tắc giao thông",
        "type": "Entity",
        "description": "Điều 7. Xử phạt, trừ điểm giấy phép lái của người điều khiển xe mô tô, xe gắn máy, các loại xe tương tự xe mô tô và các loại xe tương tự xe gắn máy vi phạm quy tắc giao thông đường bộ"
      },
      {
        "id": "d7_k7_a",
        "label": "Điểm a - Ngược chiều, đi trên vỉa hè",
        "type": "Entity",
        "description": "a) Đi ngược chiều của đường một chiều, đi ngược chiều trên đường có biển “Cấm đi ngược chiều”, trừ hành vi vi phạm quy định tại điểm b khoản này và các trường hợp xe ưu tiên đang đi làm nhiệm vụ khẩn cấp theo quy định; điều khiển xe đi trên vỉa hè, trừ trường hợp điều khiển xe đi"
      },
      {
        "id": "d7_k7_b",
        "label": "Điểm b - Đi vào đường cao tốc",
        "type": "Entity",
        "description": "b) Điều khiển xe đi vào đường cao tốc, trừ xe phục vụ việc quản lý, bảo trì đường cao tốc;"
      },
      {
        "id": "d7_k7_d",
        "label": "Điểm d - Không chấp hành hiệu lệnh người điều khiển giao thông",
        "type": "Entity",
        "description": "d) Không chấp hành hiệu lệnh, hướng dẫn của người điều khiển giao thông hoặc người kiểm soát giao thông;"
      },
      {
        "id": "d7_k7_đ",
        "label": "Điểm đ - Không nhường đường cho xe ưu tiên",
        "type": "Entity",
        "description": "đ) Không nhường đường hoặc gây cản trở xe được quyền ưu tiên đang phát tín hiệu ưu tiên đi làm nhiệm vụ."
      },
      {
        "id": "d8_k7_a",
        "label": "Điểm a - Nồng độ cồn mức 2",
        "type": "Entity",
        "description": "a) Điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn vượt quá 50 miligam đến 80 miligam/100 mililít máu hoặc vượt quá 0,25 miligam đến 0,4 miligam/1 lít khí thở;"
      },
      {
        "id": "d8_k7_b",
        "label": "Điểm b - Không chấp hành hiệu lệnh người điều khiển giao thông",
        "type": "Entity",
        "description": "b) Không chấp hành hiệu lệnh, hướng dẫn của người điều khiển giao thông hoặc người kiểm soát giao thông;"
      },
      {
        "id": "d8_k7_c",
        "label": "Điểm c - Không chấp hành hiệu lệnh đèn tín hiệu",
        "type": "Entity",
        "description": "c) Không chấp hành hiệu lệnh của đèn tín hiệu giao thông;"
      },
      {
        "id": "d8_k7_d",
        "label": "Điểm d - Đi ngược chiều",
        "type": "Entity",
        "description": "d) Đi ngược chiều của đường một chiều, đi ngược chiều trên đường có biển “Cấm đi ngược chiều”, trừ các hành vi vi phạm quy định tại điểm đ khoản 9 Điều này và các trường hợp xe ưu tiên đang đi làm nhiệm vụ khẩn cấp theo quy định."
      },
      {
        "id": "d7_k10_b",
        "label": "Điểm b - Các vi phạm khác gây tai nạn",
        "type": "Entity",
        "description": "b) Vi phạm quy định tại một trong các điểm, khoản sau của Điều này mà gây tai nạn giao thông: điểm a, điểm d, điểm đ, điểm g, điểm h, điểm i, điểm k khoản 1; điểm c, điểm đ, điểm g khoản 2; điểm b, điểm e, điểm g, điểm h, điểm k khoản 3; điểm đ khoản 4; điểm c, điểm d khoản 6; đi"
      },
      {
        "id": "hq_phat_tien_10tr_14tr",
        "label": "Phạt tiền 10.000.000đ - 14.000.000đ",
        "type": "Entity",
        "description": "Phạt tiền từ 10.000.000 đồng đến 14.000.000 đồng"
      },
      {
        "id": "d7_k10",
        "label": "Khoản 10 - Gây tai nạn giao thông (10.000.000đ - 14.000.000đ)",
        "type": "Entity",
        "description": "10. Phạt tiền từ 10.000.000 đồng đến 14.000.000 đồng đối với người điều khiển xe thực hiện một trong các hành vi vi phạm sau đây:"
      },
      {
        "id": "d7_k1_a",
        "label": "Điểm a - Không chấp hành hiệu lệnh, chỉ dẫn của biển báo, vạch kẻ đường",
        "type": "Entity",
        "description": "a) Không chấp hành hiệu lệnh, chỉ dẫn của biển báo hiệu, vạch kẻ đường, trừ các hành vi vi phạm quy định tại điểm b, điểm d, điểm e khoản 2; điểm a, điểm c, điểm d, điểm h khoản 3; điểm a, điểm b, điểm c, điểm d khoản 4; điểm b, điểm d khoản 6; điểm a, điểm b, điểm c khoản 7; điể"
      },
      {
        "id": "d7_k1_d",
        "label": "Điểm d - Chở người ngồi trên xe sử dụng ô (dù)",
        "type": "Entity",
        "description": "d) Chở người ngồi trên xe sử dụng ô (dù);"
      },
      {
        "id": "d7_k1_đ",
        "label": "Điểm đ - Không nhường đường tại nơi đường giao nhau",
        "type": "Entity",
        "description": "đ) Không tuân thủ các quy định về nhường đường tại nơi đường giao nhau, trừ các hành vi vi phạm quy định tại điểm c, điểm d khoản 6 Điều này;"
      },
      {
        "id": "d7_k1_g",
        "label": "Điểm g - Không sử dụng đèn chiếu sáng theo quy định thời gian/thời tiết",
        "type": "Entity",
        "description": "g) Không sử dụng đèn chiếu sáng trong thời gian từ 18 giờ ngày hôm trước đến 06 giờ ngày hôm sau hoặc khi có sương mù, khói, bụi, trời mưa, thời tiết xấu làm hạn chế tầm nhìn;"
      },
      {
        "id": "d7_k1_h",
        "label": "Điểm h - Tránh xe, sử dụng đèn chiếu xa, nhường đường không đúng quy định",
        "type": "Entity",
        "description": "h) Tránh xe không đúng quy định; sử dụng đèn chiếu xa khi gặp người đi bộ qua đường hoặc khi đi trên đoạn đường qua khu dân cư có hệ thống chiếu sáng đang hoạt động hoặc khi gặp xe đi ngược chiều (trừ trường hợp dải phân cách có khả năng chống chói) hoặc khi chuyển hướng xe tại n"
      },
      {
        "id": "d7_k1_i",
        "label": "Điểm i - Sử dụng còi đêm trong khu dân cư, bệnh viện",
        "type": "Entity",
        "description": "i) Sử dụng còi trong thời gian từ 22 giờ ngày hôm trước đến 05 giờ ngày hôm sau trong khu đông dân cư, khu vực cơ sở khám bệnh, chữa bệnh, trừ các xe ưu tiên đang đi làm nhiệm vụ theo quy định;"
      },
      {
        "id": "d7_k1_k",
        "label": "Điểm k - Chạy dưới tốc độ tối thiểu",
        "type": "Entity",
        "description": "k) Điều khiển xe chạy dưới tốc độ tối thiểu trên đoạn đường bộ có quy định tốc độ tối thiểu cho phép."
      },
      {
        "id": "d7_k2_c",
        "label": "Điểm c - Chạy tốc độ thấp không đi bên phải gây cản trở",
        "type": "Entity",
        "description": "c) Điều khiển xe chạy tốc độ thấp mà không đi bên phải phần đường xe chạy gây cản trở giao thông;"
      },
      {
        "id": "d7_k2_đ",
        "label": "Điểm đ - Lắp đặt, sử dụng thiết bị phát tín hiệu xe ưu tiên trái phép",
        "type": "Entity",
        "description": "đ) Xe không được quyền ưu tiên lắp đặt, sử dụng thiết bị phát tín hiệu của xe được quyền ưu tiên;"
      },
      {
        "id": "d7_k2_g",
        "label": "Điểm g - Chở quá số người quy định (02 người)",
        "type": "Entity",
        "description": "g) Chở theo 02 người trên xe, trừ trường hợp chở người bệnh đi cấp cứu, trẻ em dưới 12 tuổi, người già yếu hoặc người khuyết tật, áp giải người có hành vi vi phạm pháp luật;"
      },
      {
        "id": "d7_k3_b",
        "label": "Điểm b - Chở theo từ 03 người trở lên",
        "type": "Entity",
        "description": "b) Chở theo từ 03 người trở lên trên xe;"
      },
      {
        "id": "d7_k3_e",
        "label": "Điểm e - Bám, kéo, đẩy, mang vác vật cồng kềnh, đứng trên yên",
        "type": "Entity",
        "description": "e) Người đang điều khiển xe hoặc chở người ngồi trên xe bám, kéo, đẩy xe khác, vật khác, dẫn dắt vật nuôi, mang vác vật cồng kềnh; chở người đứng trên yên, giá đèo hàng hoặc ngồi trên tay lái của xe;"
      },
      {
        "id": "d7_k3_g",
        "label": "Điểm g - Điều khiển xe kéo theo xe khác, vật khác",
        "type": "Entity",
        "description": "g) Điều khiển xe kéo theo xe khác, vật khác;"
      },
      {
        "id": "d7_k3_h",
        "label": "Điểm h - Không đèn chiếu gần trong hầm",
        "type": "Entity",
        "description": "h) Chạy trong hầm đường bộ không sử dụng đèn chiếu sáng gần;"
      },
      {
        "id": "d7_k3_k",
        "label": "Điểm k - Chạy dàn hàng ngang từ 03 xe trở lên",
        "type": "Entity",
        "description": "k) Điều khiển xe chạy dàn hàng ngang từ 03 xe trở lên;"
      },
      {
        "id": "d7_k4_đ",
        "label": "Điểm đ - Sử dụng ô, điện thoại, thiết bị âm thanh",
        "type": "Entity",
        "description": "đ) Người đang điều khiển xe sử dụng ô (dù), thiết bị âm thanh (trừ thiết bị trợ thính), dùng tay cầm và sử dụng điện thoại hoặc các thiết bị điện tử khác."
      },
      {
        "id": "d7_k6_c",
        "label": "Điểm c - Không nhường đường khi từ đường nhánh ra đường chính",
        "type": "Entity",
        "description": "c) Không giảm tốc độ (hoặc dừng lại) và nhường đường khi điều khiển xe đi từ đường không ưu tiên ra đường ưu tiên, từ đường nhánh ra đường chính;"
      },
      {
        "id": "d7_k6_d",
        "label": "Điểm d - Không nhường đường tại nơi giao nhau/vòng xuyến",
        "type": "Entity",
        "description": "d) Không giảm tốc độ và nhường đường cho xe đi đến từ bên phải tại nơi đường giao nhau không có báo hiệu đi theo vòng xuyến; không giảm tốc độ và nhường đường cho xe đi đến từ bên trái tại nơi đường giao nhau có báo hiệu đi theo vòng xuyến."
      },
      {
        "id": "d7_k9_a",
        "label": "Điểm a - Lạng lách, đánh võng, quệt chân chống",
        "type": "Entity",
        "description": "a) Điều khiển xe lạng lách, đánh võng trên đường bộ; sử dụng chân chống hoặc vật khác quệt xuống đường khi xe đang chạy;"
      },
      {
        "id": "d7_k9_b",
        "label": "Điểm b - Nhóm xe chạy quá tốc độ",
        "type": "Entity",
        "description": "b) Điều khiển xe thành nhóm từ 02 xe trở lên chạy quá tốc độ quy định;"
      },
      {
        "id": "d7_k9_h",
        "label": "Điểm h - Ngồi sau điều khiển xe",
        "type": "Entity",
        "description": "h) Ngồi phía sau vòng tay qua người ngồi trước để điều khiển xe, trừ trường hợp chở trẻ em dưới 06 tuổi ngồi phía trước;"
      },
      {
        "id": "d7_k9_k",
        "label": "Điểm k - Rú ga, nẹt pô liên tục",
        "type": "Entity",
        "description": "k) Sử dụng còi, rú ga (nẹt pô) liên tục trong khu đông dân cư, khu vực cơ sở khám bệnh, chữa bệnh, trừ các xe ưu tiên đang đi làm nhiệm vụ theo quy định."
      },
      {
        "id": "d7_k13_b",
        "label": "Trừ điểm giấy phép lái xe 04 điểm",
        "type": "Entity",
        "description": "b) Thực hiện hành vi quy định tại điểm đ khoản 4; điểm a khoản 6; điểm c, điểm d, điểm đ khoản 7; điểm a khoản 8 Điều này bị trừ điểm giấy phép lái xe 04 điểm"
      },
      {
        "id": "d7_k13",
        "label": "Khoản 13 - Trừ điểm giấy phép lái xe",
        "type": "Entity",
        "description": "13. Ngoài việc bị áp dụng hình thức xử phạt, người điều khiển xe thực hiện hành vi vi phạm còn bị trừ điểm giấy phép lái xe như sau:"
      },
      {
        "id": "d7_k6_a",
        "label": "Điểm a - Nồng độ cồn mức thấp",
        "type": "Entity",
        "description": "a) Điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn nhưng chưa vượt quá 50 miligam/100 mililít máu hoặc chưa vượt quá 0,25 miligam/1 lít khí thở;"
      },
      {
        "id": "d7_k8_a",
        "label": "Điểm a - Chạy quá tốc độ trên 20 km/h",
        "type": "Entity",
        "description": "a) Điều khiển xe chạy quá tốc độ quy định trên 20 km/h;"
      }
    ],
    "edges": [
      {
        "source": "d7_k7_c",
        "target": "vuot_den_do",
        "relation": "QUY_DINH_TAI"
      },
      {
        "source": "vuot_den_do",
        "target": "hq_phat_4000_6000",
        "relation": "DAN_DEN_HAU_QUA"
      },
      {
        "source": "vuot_den_do",
        "target": "nguoi_dieu_khien_xe_mo_to",
        "relation": "THUC_HIEN"
      },
      {
        "source": "d7_k7_c",
        "target": "d7_k7",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "dieu_7",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d7_k7_a",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d7_k7_b",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d7_k7_d",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d7_k7_đ",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d8_k7_a",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d8_k7_b",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d8_k7_c",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7",
        "target": "d8_k7_d",
        "relation": "THUOC"
      },
      {
        "source": "d7_k7_c",
        "target": "d7_k10_b",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "hq_phat_tien_10tr_14tr",
        "relation": "QUY_DINH_TAI"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k10",
        "relation": "THUOC"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_a",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_d",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_g",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_h",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_i",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k1_k",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k2_c",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k2_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k2_g",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k3_b",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k3_e",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k3_g",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k3_h",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k3_k",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k4_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k6_c",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k6_d",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k7_d",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k7_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k9_a",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k9_b",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k9_h",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k10_b",
        "target": "d7_k9_k",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k7_c",
        "target": "d7_k13_b",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k13",
        "relation": "THUOC"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k4_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k6_a",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k7_d",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k7_đ",
        "relation": "THAM_CHIEU_DEN"
      },
      {
        "source": "d7_k13_b",
        "target": "d7_k8_a",
        "relation": "THAM_CHIEU_DEN"
      }
    ]
  }
}
```

### Response lỗi thường gặp
- `404`: Không tìm thấy path cho `id` được truyền.
- `503`: FastAPI không kết nối được Neo4j.
- `500`: Lỗi nội bộ khi truy vấn/parse graph.

### Mô tả dữ liệu
- `seed_id`: ID node đầu vào dùng để dựng subgraph.
- `query`: Câu truy vấn Cypher backend đang dùng để lấy path.
- `type_meta`: Gợi ý UI (màu sắc, icon) theo Type của node, Frontend có thể dùng để map trực tiếp lên UI (Vis.js / React Flow / Echarts ...).
- `nodes`: Chứa danh sách các đỉnh của đồ thị. 
  - `id`: Định danh duy nhất.
  - `type`: Phân loại node (HanhVi, PhuongTien, MucPhat... hoặc `Entity` fallback). Đem type này map với `type_meta` để lấy theme tương ứng.
- `edges`: Chứa danh sách các liên kết. 
  - `source`, `target`: ID của 2 node tham gia liên kết.
  - `relation`: Tên quan hệ nối giữa 2 node (vd: `BI_XU_PHAT`, `QUY_DINH_TAI`, `HUONG_DAN_THI_HANH`).
