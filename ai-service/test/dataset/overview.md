# Tổng quan bộ dataset đánh giá (lexmind-eval)

Tài liệu này mô tả cấu trúc dữ liệu dùng để đánh giá pipeline hỏi đáp luật giao thông. Mục tiêu là đo được cả 3 lớp năng lực:

- Trả lời đúng theo căn cứ pháp lý.
- Truy xuất đúng nguồn (graph/document).
- Hành xử an toàn khi gặp câu ngoài phạm vi hoặc câu mơ hồ.

## 1) Schema của mỗi sample

Mỗi dòng dữ liệu là một object JSON với các trường sau.

| Field | Type | Mô tả / ví dụ |
|---|---|---|
| question | string | Câu hỏi gốc từ user, giữ nguyên wording tự nhiên. |
| ground_truth | string | Câu trả lời chuẩn viết tay, không sinh bởi LLM. |
| reference_nodes | list[string] | Danh sách node ID trong Neo4j làm căn cứ chính, ví dụ: ["nd168_dieu5_khoan3", "ldb2024_dieu8"]. |
| difficulty | enum | easy \\| medium \\| hard \\| adversarial |
| question_type | enum | factual \\| multi_hop \\| comparison \\| adversarial \\| oos |
| expected_behavior | enum | answer \\| refuse \\| clarify |
| source_docs | list[string] | Mã văn bản liên quan, ví dụ: ["nd168_2024", "ldb_2024"]. |
| tags | list[string] | Tag để filter khi eval/debug, ví dụ: ["xe_may", "vuot_den_do", "muc_phat"]. |

Ghi chú:

- reference_nodes là trường quan trọng để đánh giá chất lượng retrieval theo graph.
- source_docs dùng để đối chiếu nguồn ở cấp văn bản.
- tags giúp cắt lát kết quả theo chủ đề, loại vi phạm, loại phương tiện.

## 2) Ý nghĩa các nhãn hành vi

- answer: Hệ thống phải trả lời trực tiếp, có căn cứ.
- refuse: Hệ thống phải từ chối đúng chuẩn vì câu hỏi ngoài phạm vi.
- clarify: Hệ thống phải hỏi làm rõ thay vì tự suy diễn.

Khuyến nghị khi ghi dữ liệu:

- Với refuse hoặc clarify, có thể để ground_truth rỗng hoặc mô tả ngắn kỳ vọng hành vi.
- Không gán answer cho câu thiếu thông tin trọng yếu.

## 3) Mức độ khó và loại câu hỏi

- easy: 1 fact, 1 node, suy luận tối thiểu.
- medium: cần nối 2-3 node hoặc 2 điều khoản liên quan.
- hard: cần so sánh cũ/mới, nhiều điều kiện, dễ nhầm.
- adversarial: chứa premise sai, câu gây nhiễu hoặc cố bẫy hệ thống.

Phân loại question_type:

- factual: hỏi một thông tin cụ thể.
- multi_hop: cần kết hợp nhiều căn cứ.
- comparison: đối chiếu nhiều mốc luật/văn bản.
- adversarial: câu có giả định sai hoặc đánh lạc hướng.
- oos: ngoài phạm vi domain pháp luật giao thông đang hỗ trợ.

## 4) Phân bố mẫu đề xuất (tối thiểu 60 sample)

- easy (factual, 1 node): 20 câu.
- medium (multi_hop, 2-3 node): 20 câu.
- hard (comparison cũ/mới): 10 câu.
- adversarial (câu gây nhiễu): 10 câu.
- out-of-scope (pipeline phải refuse): 5 câu.
- ambiguous (pipeline phải clarify): 5 câu.

Mục tiêu của phân bố này là tránh lệch về câu dễ, đồng thời đảm bảo đo được độ bền của pipeline khi gặp input khó hoặc không chuẩn.

## 5) Ví dụ một sample chuẩn

```json
{
  "question": "Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?",
  "ground_truth": "Theo Nghị định 168/2024/NĐ-CP, người điều khiển xe máy vượt đèn đỏ bị phạt từ ...",
  "reference_nodes": ["nd168_dieu6_khoan4_diema"],
  "difficulty": "easy",
  "question_type": "factual",
  "expected_behavior": "answer",
  "source_docs": ["nd168_2024"],
  "tags": ["xe_may", "vuot_den_do", "muc_phat"]
}
```

## 6) Checklist chất lượng dữ liệu

- Câu hỏi bám đúng phạm vi pháp luật giao thông (trừ nhóm oos chủ đích).
- ground_truth có căn cứ, không mơ hồ và không mâu thuẫn với văn bản nguồn.
- reference_nodes truy vết được trong graph.
- source_docs khớp với căn cứ thực tế dùng trong ground_truth.
- expected_behavior phù hợp bản chất câu hỏi (answer/refuse/clarify).
- Tên tag thống nhất, không trùng nghĩa khác cách viết.

Khi mở rộng dataset, ưu tiên thêm sample vào các nhóm có hiệu năng thấp để tăng giá trị chẩn đoán của bộ eval.