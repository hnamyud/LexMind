import os
import re

from typing_extensions import Annotated, TypedDict
from langchain_openai import ChatOpenAI


grader_llm = ChatOpenAI(
    model=os.getenv("LLM_ROUTER"),
    api_key=os.getenv("LOCAL_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    temperature=0,

    extra_body={
        "thinking": {"type": "disabled"}
    },
    max_tokens=4096,
    )

# ── Helpers ────────────────────────────────────────────────────────────────

def _get_expected_behavior(inputs: dict, reference_outputs: dict) -> str:
    """Lấy expected_behavior từ inputs hoặc reference_outputs, mặc định 'answer'."""
    return (
        (inputs or {}).get("expected_behavior")
        or (reference_outputs or {}).get("expected_behavior")
        or "answer"
    )

def _skip_result(key: str, reason: str) -> dict:
    """Tạo kết quả skip hợp lệ cho LangSmith."""
    return {"key": key, "score": None, "comment": reason}


def _node_id_from_citation(citation: str) -> str | None:
    text = (citation or "").strip()
    if not text:
        return None
    low = text.lower()
    if "nghị định 168" in low or "nghi dinh 168" in low:
        doc_ref = "nd168_2024"
    elif "luật trật tự" in low or "luat trat tu" in low:
        doc_ref = "l36_2024"
    elif "luật đường bộ" in low or "luat duong bo" in low:
        doc_ref = "l35_2024"
    else:
        doc_ref = None

    article_m = re.search(r"[Đđ]iều\s*(\d+)", text)
    clause_m = re.search(r"[Kk]hoản\s*(\d+)", text)
    point_m = re.search(r"[Đđ]iểm\s*([a-zđ])", text)
    if not doc_ref or not article_m:
        return None

    node_id = f"{doc_ref}_d{article_m.group(1)}"
    if clause_m:
        node_id += f"_k{clause_m.group(1)}"
    if point_m:
        node_id += f"_{point_m.group(1).lower()}"
    return node_id


def _reference_nodes_from_citations(citations: list[str]) -> list[str]:
    seen: set[str] = set()
    nodes: list[str] = []
    for citation in citations or []:
        node_id = _node_id_from_citation(str(citation))
        if node_id and node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
    return nodes

# ── Evaluator 1: Correctness ──────────────────────────────────────────────
class CorrectnessGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích từng bước lý do chấm điểm"]
    score: Annotated[float, ..., "Điểm số: 0.0 | 0.25 | 0.5 | 0.75 | 1.0"]

CORRECTNESS_PROMPT = """Bạn là chuyên gia pháp lý chấm điểm câu trả lời về luật giao thông Việt Nam.
Phạm vi: Nghị định 168/2024/NĐ-CP, Luật Trật tự ATGT đường bộ 2024 (Luật 36/2024), Luật Đường bộ 2024 (Luật 35/2024).

Chấm theo thang 5 mức:
1.00 — Hoàn toàn đúng: mức phạt đúng min-max, đúng loại xe, hình phạt bổ sung đúng (nếu được hỏi).
0.75 — Đúng chính, sai phụ: mức phạt chính đúng nhưng thiếu/sai hình phạt bổ sung (tước bằng, trừ điểm).
0.50 — Đúng một phần: đúng khung phạt chung nhưng sai chi tiết (sai 1 con số, nhầm loại xe không đáng kể).
0.25 — Sai nhiều: đề cập đúng chủ đề nhưng sai phần lớn thông tin quan trọng (sai mức phạt chính).
0.00 — Hoàn toàn sai hoặc không trả lời: thông tin trái ngược ground truth hoặc bot từ chối.

Lưu ý:
- KHÔNG yêu cầu cite điều khoản chính xác — chỉ chấm nội dung pháp lý.
- Với câu hỏi quy định/định nghĩa: đúng ý chính = 1.0, đúng một phần = 0.5.
- Trả về score là một trong: 0.0, 0.25, 0.5, 0.75, 1.0

Trả lời đúng schema json của evaluator."""

def correctness(inputs: dict, outputs: dict, reference_outputs: dict) -> bool | dict:
    """
    Chấm tính đúng đắn pháp lý của câu trả lời.

    Skip rules:
    - refuse: Không có con số/điều khoản để check đúng/sai → skip (None).
    - clarify: Bot chưa được phép đưa ra con số → skip (None).
              Nếu Bot đưa ra con số dù thiếu thông tin → đánh lỗi ở behavior_compliance.
    - answer:  Chấm bình thường.
    """
    expected_behavior = _get_expected_behavior(inputs, reference_outputs)

    # Skip với refuse và clarify
    if expected_behavior in ("refuse", "clarify"):
        return _skip_result("correctness", f"skipped: expected_behavior={expected_behavior}")

    grader = grader_llm.with_structured_output(CorrectnessGrade, method="json_schema")
    student_answer = (outputs or {}).get("answer", "")
    if not student_answer:
        return False

    # LangSmith dataset dùng "ground_truth" (cả inputs lẫn reference_outputs)
    # Thứ tự ưu tiên: reference_outputs.ground_truth → inputs.ground_truth → reference_outputs.answer
    ground_truth = (
        (reference_outputs or {}).get("ground_truth")
        or (inputs or {}).get("ground_truth")
        or (reference_outputs or {}).get("answer")
        or ""
    )
    if not ground_truth:
        # Không có ground truth → không thể chấm correctness
        return False

    prompt = f"""QUESTION: {inputs.get('question', '')}
GROUND TRUTH: {ground_truth}
STUDENT ANSWER: {student_answer}"""

    grade = grader.invoke([
        {"role": "system", "content": CORRECTNESS_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return 0.0
    raw = grade.get("score", 0.0)
    # Snap về mức gần nhất trong [0, 0.25, 0.5, 0.75, 1.0]
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    return min(levels, key=lambda x: abs(x - float(raw)))


# ── Evaluator 2: Behavior Compliance ────────────────────────────────────
class BehaviorGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích hành vi AI có khớp expected_behavior không"]
    compliant: Annotated[bool, ..., "True nếu AI hành xử đúng theo expected_behavior"]

BEHAVIOR_PROMPT = """Kiểm tra xem AI có hành xử đúng theo expected_behavior không.

Quy tắc:
- expected_behavior = "answer"   → AI phải trả lời trực tiếp có nội dung pháp lý cụ thể.
- expected_behavior = "refuse"   → AI phải từ chối lịch sự và nêu đúng lý do ngoài phạm vi.
                                   AI có thể nói "Tôi không biết" hoặc redirect — vẫn compliant.
                                   Nếu AI bịa ra thông tin pháp lý hoặc trả lời tùy tiện → Not compliant.
- expected_behavior = "clarify"  → AI phải hỏi lại để làm rõ những thông tin còn thiếu
                                   (ví dụ: loại xe, vận tốc cụ thể) thay vì tự trả lời.
                                   Nếu AI đưa ra con số tiền phạt khi chưa đủ thông tin → Not compliant.

Chú ý QUAN TRỌNG:
- Với "answer": Chỉ cần AI có nội dung pháp lý đúng (mức phạt, điều khoản).
  KHÔNG phạt nếu format khác (dùng header thay bullet, có lời chào đầu...).
  CHỈ Not compliant nếu AI từ chối hoặc hoàn toàn không trả lời câu hỏi.
  Việc AI trả lời đầy đủ LUẬT + thêm 1 câu hỏi làm rõ (để tránh nhầm lẫn cho người dùng) là hành vi TỐT và thông minh. KHÔNG ĐƯỢC chấm Not compliant trong trường hợp này.
  Chỉ phạt "answer" nếu AI không đưa ra được con số/điều khoản mà lại đi hỏi ngược lại khách hàng từ đầu đến cuối.
- Với "clarify": Bot phải HỎI LẠI. Nếu bot vừa hỏi lại VÀ vừa đưa ra
  mức phạt tham khảo thì vẫn có thể compliant — miễn là câu hỏi làm rõ
  được đặt rõ ràng.

Trả lời đúng schema json của evaluator."""

def behavior_compliance(inputs: dict, outputs: dict, reference_outputs: dict) -> bool:
    """
    Kiểm tra AI có hành xử đúng expected_behavior (answer/refuse/clarify) không.

    Đây là evaluator DUY NHẤT luôn được chấm với MỌI expected_behavior.
    - refuse: Kiểm tra Bot từ chối lịch sự và đúng lý do.
    - clarify: Kiểm tra Bot liệt kê đúng thông tin còn thiếu và KHÔNG đưa ra con số.
    - answer:  Kiểm tra Bot trả lời trực tiếp có nội dung pháp lý.
    """
    grader = grader_llm.with_structured_output(BehaviorGrade, method="json_schema")
    student_answer = (outputs or {}).get("answer", "")
    verdict = (outputs or {}).get("verdict", "")

    expected_behavior = _get_expected_behavior(inputs, reference_outputs)

    if not student_answer and not verdict:
        # Không có output gì cả
        return expected_behavior == "refuse"

    prompt = f"""QUESTION: {inputs.get('question', '')}
EXPECTED BEHAVIOR: {expected_behavior}
AI VERDICT: {verdict}
AI ANSWER: {student_answer}"""

    grade = grader.invoke([
        {"role": "system", "content": BEHAVIOR_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return False
    return grade.get("compliant", False)


# ── Evaluator 3: Groundedness ─────────────────────────────────────────────
class GroundednessGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích từng bước"]
    score: Annotated[float, ..., "Điểm số: 0.0 | 0.25 | 0.5 | 0.75 | 1.0"]

GROUNDEDNESS_PROMPT = """Bạn là chuyên gia pháp lý kiểm tra hallucination trong câu trả lời về luật giao thông Việt Nam.
Phạm vi: Nghị định 168/2024/NĐ-CP, Luật Trật tự ATGT đường bộ 2024 (Luật 36/2024), Luật Đường bộ 2024 (Luật 35/2024).

FACTS được cung cấp:
  [node_id | Vị trí điều/khoản | Tên văn bản]
  Nội dung: <nội dung điều khoản gốc>
  → Hậu quả/Mức phạt: <mức phạt tiền, tước GPLX, ...>
  → Áp dụng cho: <loại phương tiện/đối tượng>

Chấm theo thang 5 mức:
1.00 — Hoàn toàn có căn cứ: mọi số tiền, điều khoản đều có trong FACTS.
0.75 — Phần lớn có căn cứ: thông tin chính đúng, có 1 chi tiết nhỏ không xác minh được (không mâu thuẫn).
0.50 — Một phần có căn cứ: thông tin cốt lõi đúng nhưng có thêm thông tin không rõ nguồn gốc (không sai rõ ràng).
0.25 — Ít có căn cứ: phần lớn thông tin không xác minh được hoặc có 1 điểm hallucinate nhỏ.
0.00 — Hallucinate: bịa số tiền phạt, bịa điều khoản, hoặc mâu thuẫn rõ ràng với FACTS.

Lưu ý:
- Cho phép diễn giải, paraphrase, tổng hợp từ nhiều FACTS miễn là đúng ý.
- Thêm lời giải thích/tư vấn chung không mâu thuẫn FACTS → không phạt.
- Trả về score là một trong: 0.0, 0.25, 0.5, 0.75, 1.0

Trả lời đúng schema json của evaluator."""

def groundedness(inputs: dict, outputs: dict, reference_outputs: dict = None) -> bool | dict:
    """
    Kiểm tra câu trả lời có bị hallucinate so với retrieved context không.

    Skip rules:
    - refuse: Bot không được phép (và thường sẽ không) dẫn luật khi từ chối → skip (None).
              Nếu Bot dẫn luật khi từ chối → đánh lỗi ở behavior_compliance.
    - clarify: Tương tự, không có (hoặc không nên có) context liên quan → skip (None).
    - answer:  Chấm bình thường.
    """
    expected_behavior = _get_expected_behavior(inputs, reference_outputs or {})

    # Skip với refuse và clarify
    if expected_behavior in ("refuse", "clarify"):
        return _skip_result("groundedness", f"skipped: expected_behavior={expected_behavior}")

    grader = grader_llm.with_structured_output(GroundednessGrade, method="json_schema")

    # Ưu tiên groundedness_context (plain text đã reformat) — dễ đọc hơn cho grader
    context = (
        (outputs or {}).get("groundedness_context")
        or (outputs or {}).get("citation_context")
        or (outputs or {}).get("grading_context")
        or (outputs or {}).get("context", "")
    )
    student_answer = (outputs or {}).get("answer", "")
    if not student_answer:
        return False
    if not context:
        return _skip_result("groundedness", "skipped: missing context")

    prompt = f"FACTS:\n{context}\n\nSTUDENT ANSWER:\n{student_answer}"
    grade = grader.invoke([
        {"role": "system", "content": GROUNDEDNESS_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return 0.0
    raw = grade.get("score", 0.0)
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    return min(levels, key=lambda x: abs(x - float(raw)))


# ── Evaluator 4: Citation Accuracy ───────────────────────────────────────
class CitationGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích từng bước"]
    matched: Annotated[int, ..., "Số expected citations được cite đúng"]
    total: Annotated[int, ..., "Tổng số expected citations"]

CITATION_PROMPT = """Kiểm tra tính chính xác của trích dẫn điều khoản pháp lý.

Bạn được cung cấp EXPECTED CITATIONS — danh sách điều khoản lẽ ra phải được trích dẫn.
Đếm xem STUDENT ANSWER cite đúng bao nhiêu.

Quy tắc MATCH (format khác nhau nhưng cùng điều khoản = MATCH):
- "khoản 2 Điều 58" = "Điều 58 khoản 2" → MATCH
- "Điều 7 điểm c khoản 7" = "Điều 7 khoản 7 điểm c" → MATCH
- "Nghị định 168" = "NĐ 168/2024" = "Nghị định 168/2024/NĐ-CP" → MATCH

Yêu cầu output:
- matched: số citations trong EXPECTED CITATIONS mà bot cite đúng (0 đến total)
- total: tổng số citations trong EXPECTED CITATIONS
- Chỉ xét citation trong câu trả lời chính.

Trả lời đúng schema json của evaluator."""

def citation_accuracy(inputs: dict, outputs: dict, reference_outputs: dict = None) -> bool | dict:
    """
    Kiểm tra tính chính xác của citation điều khoản trong câu trả lời.
    Chấm dựa trên expected_citations từ dataset (thay vì so với retrieved context).

    Skip rules:
    - refuse: Bot từ chối → skip (None).
    - answer/clarify: Chấm bình thường.
    """
    expected_behavior = _get_expected_behavior(inputs, reference_outputs or {})

    # Skip với refuse
    if expected_behavior == "refuse":
        return _skip_result("citation_accuracy", "skipped: expected_behavior=refuse")

    # Lấy expected_citations từ reference_outputs (dataset)
    expected_citations: list[str] = (
        (reference_outputs or {}).get("expected_citations")
        or (inputs or {}).get("expected_citations")
        or []
    )
    if not expected_citations:
        # Không có expected_citations → không thể chấm
        return _skip_result("citation_accuracy", "skipped: no expected_citations in dataset")

    grader = grader_llm.with_structured_output(CitationGrade, method="json_schema")
    student_answer = (outputs or {}).get("answer", "")
    if not student_answer:
        return False

    citations_text = "\n".join(f"- {c}" for c in expected_citations)
    prompt = f"EXPECTED CITATIONS:\n{citations_text}\n\nSTUDENT ANSWER:\n{student_answer}"

    grade = grader.invoke([
        {"role": "system", "content": CITATION_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return 0.0
    matched = int(grade.get("matched", 0))
    total = int(grade.get("total", 1)) or 1
    ratio = matched / total
    # Snap về mức gần nhất trong 5 mức
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    return min(levels, key=lambda x: abs(x - ratio))


# ── Evaluator 5: Retrieval Node Match ────────────────────────────────────
def retrieval_node_match(inputs: dict, outputs: dict, reference_outputs: dict) -> float | dict:
    """
    So sánh node IDs đã retrieve với reference_nodes trong dataset.

    Skip rules:
    - refuse: Câu OOS mà bốc được node thì thường là bốc nhầm → không nên reward → skip (None).
    - clarify: Rất quan trọng! Bot phải bốc đúng node mới biết hỏi lại gì → chấm bình thường.
    - answer:  Chấm bình thường.

    Returns
    -------
    float | None :
        - None nếu skip (refuse)
        - None nếu không có reference_nodes (không đánh giá được)
        - tỉ lệ hit [0.0, 1.0] = |retrieved ∩ reference| / |reference|
    """
    expected_behavior = _get_expected_behavior(inputs, reference_outputs)

    # Skip với refuse: câu OOS không nên bốc được node nào
    if expected_behavior == "refuse":
        return _skip_result("retrieval_node_match", "skipped: expected_behavior=refuse")

    # reference_nodes nằm ở reference_outputs (LangSmith dataset) hoặc inputs (local)
    ref_nodes: list[str] = (
        (reference_outputs or {}).get("reference_nodes")
        or (inputs or {}).get("reference_nodes")
        or []
    )
    if not ref_nodes:
        expected_citations = (
            (reference_outputs or {}).get("expected_citations")
            or (inputs or {}).get("expected_citations")
            or []
        )
        ref_nodes = _reference_nodes_from_citations(expected_citations)
    retrieved_nodes: list[str] = (
        (outputs or {}).get("retrieved_nodes_legal")
        or (outputs or {}).get("retrieved_nodes")
        or []
    )

    if not ref_nodes:
        return _skip_result("retrieval_node_match", "skipped: missing reference_nodes")

    ref_set = set(ref_nodes)
    ret_set = set(retrieved_nodes)
    hit_rate = len(ref_set & ret_set) / len(ref_set)
    return round(hit_rate, 4)
