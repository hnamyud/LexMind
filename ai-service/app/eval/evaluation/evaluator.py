import os

from typing_extensions import Annotated, TypedDict
from langchain_openai import ChatOpenAI


grader_llm = ChatOpenAI(
    model=os.getenv("LLM_DIRECT"),
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

# ── Evaluator 1: Correctness ──────────────────────────────────────────────
class CorrectnessGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích từng bước lý do chấm điểm"]
    correct: Annotated[bool, ..., "True nếu câu trả lời đúng về mức phạt và điều khoản"]

CORRECTNESS_PROMPT = """Bạn là chuyên gia pháp lý chấm điểm câu trả lời về Nghị định 168/2024/NĐ-CP.

Tiêu chí chấm (theo thứ tự ưu tiên):
(1) Mức phạt tiền phải đúng khoảng min-max — sai 1 triệu là sai.
(2) Phân biệt đúng loại phương tiện nếu câu hỏi hỏi cụ thể (xe máy ≠ ô tô).
(3) Hình phạt bổ sung (tước GPLX, trừ điểm, tạm giữ xe) phải đúng nếu được đề cập.
(4) Cho phép thêm thông tin bổ sung miễn là không mâu thuẫn với ground truth.
(5) KHÔNG yêu cầu cite điều khoản chính xác — chỉ chấm nội dung pháp lý.

Correct = True chỉ khi đáp ứng đủ tiêu chí (1) và (2). (3) là optional.

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
        return False
    return grade.get("correct", False)


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
    grounded: Annotated[bool, ..., "True nếu không hallucinate mức phạt hoặc điều khoản"]

GROUNDEDNESS_PROMPT = """Bạn là chuyên gia pháp lý kiểm tra hallucination trong câu trả lời về NĐ 168.

Kiểm tra theo thứ tự:
(1) Mọi mức phạt tiền (số tiền cụ thể) phải có trong FACTS — không được tự nghĩ ra.
(2) Mọi điều khoản được cite (Điều X, Khoản Y) phải xuất hiện trong FACTS.
(3) Hình phạt bổ sung phải có căn cứ trong FACTS.
(4) Cho phép diễn giải và tổng hợp từ FACTS miễn là không thêm thông tin pháp lý mới.

Grounded = False nếu phát hiện bất kỳ số tiền hoặc điều khoản nào không có trong FACTS.

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
        # Không có context → không thể kiểm tra groundedness
        return False
    prompt = f"FACTS:\n{context}\n\nSTUDENT ANSWER:\n{student_answer}"
    grade = grader.invoke([
        {"role": "system", "content": GROUNDEDNESS_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return False
    return grade.get("grounded", False)


# ── Evaluator 4: Citation Accuracy ───────────────────────────────────────
class CitationGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích từng bước"]
    citation_accurate: Annotated[bool, ..., "True nếu mọi citation đều đúng hoặc không có citation"]

CITATION_PROMPT = """Kiểm tra tính chính xác của trích dẫn điều khoản trong câu trả lời về NĐ 168/2024.

Quy tắc:
(1) Nếu không có citation nào → citation_accurate = True (không bắt buộc cite).
(2) Citation phải đúng format: [Điều X, Khoản Y, Điểm Z, Nghị định 168/2024/NĐ-CP].
(3) Điều khoản được cite phải xuất hiện trong CONTEXT (graph node IDs hoặc raw_text).
(4) Mức phạt gắn với citation phải khớp với nội dung điều khoản đó trong CONTEXT.

Citation = False chỉ khi:
- Cite điều khoản không tồn tại trong CONTEXT.
- Cite Điều X nhưng gắn với mức phạt của Điều Y.

Trả lời đúng schema json của evaluator."""

def citation_accuracy(inputs: dict, outputs: dict, reference_outputs: dict = None) -> bool | dict:
    """
    Kiểm tra tính chính xác của citation điều khoản trong câu trả lời.

    Skip rules:
    - refuse: Bot từ chối → không được phép dẫn luật linh tinh → skip (None).
              Nếu Bot dẫn luật khi từ chối → đánh lỗi ở behavior_compliance.
    - clarify: Optional — Bot có thể cite làm tiền đề hỏi lại ("Theo Điều 6...").
               Vẫn chấm bình thường để phát hiện citation sai dù là câu clarify.
    - answer:  Chấm bình thường.
    """
    expected_behavior = _get_expected_behavior(inputs, reference_outputs or {})

    # Skip với refuse: Bot không được phép dẫn luật khi từ chối
    if expected_behavior == "refuse":
        return _skip_result("citation_accuracy", "skipped: expected_behavior=refuse")

    # Với clarify và answer: chấm bình thường
    grader = grader_llm.with_structured_output(CitationGrade, method="json_schema")
    context = (
        (outputs or {}).get("citation_context")
        or (outputs or {}).get("grading_context")
        or (outputs or {}).get("context", "")
    )
    student_answer = (outputs or {}).get("answer", "")
    if not student_answer:
        return False
    prompt = f"CONTEXT:\n{context}\n\nANSWER:\n{student_answer}"
    grade = grader.invoke([
        {"role": "system", "content": CITATION_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    if not isinstance(grade, dict):
        return False
    return grade.get("citation_accurate", False)


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
        - 1.0 nếu không có reference_nodes (không đánh giá được)
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
    retrieved_nodes: list[str] = (
        (outputs or {}).get("retrieved_nodes_legal")
        or (outputs or {}).get("retrieved_nodes")
        or []
    )

    if not ref_nodes:
        # Dataset không có reference_nodes → skip (trả 1.0 để không kéo thấp tổng)
        return 1.0

    ref_set = set(ref_nodes)
    ret_set = set(retrieved_nodes)
    hit_rate = len(ref_set & ret_set) / len(ref_set)
    return round(hit_rate, 4)