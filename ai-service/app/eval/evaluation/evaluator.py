import os

from typing_extensions import Annotated, TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI

# Dùng Gemini Flash làm grader — rẻ hơn GPT-4, đủ tốt cho legal domain
grader_llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
)

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

Correct = True chỉ khi đáp ứng đủ tiêu chí (1) và (2). (3) là optional."""

def correctness(inputs: dict, outputs: dict, reference_outputs: dict) -> bool:
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
    return grade["correct"]


# ── Evaluator 2: Behavior Compliance ────────────────────────────────────
class BehaviorGrade(TypedDict):
    explanation: Annotated[str, ..., "Giải thích hành vi AI có khớp expected_behavior không"]
    compliant: Annotated[bool, ..., "True nếu AI hành xử đúng theo expected_behavior"]

BEHAVIOR_PROMPT = """Kiểm tra xem AI có hành xử đúng theo expected_behavior không.

Quy tắc:
- expected_behavior = "answer"   → AI phải trả lời trực tiếp có nội dung pháp lý cụ thể.
- expected_behavior = "refuse"   → AI phải từ chối hoặc nói rõ ngoài phạm vi hỗ trợ.
- expected_behavior = "clarify"  → AI phải hỏi lại để làm rõ thay vì tự trả lời.

Chú ý:
- Với "refuse": AI có thể nói "Tôi không biết" hoặc redirect — đó vẫn là compliant.
- Với "answer": Nếu AI từ chối câu có thể trả lời được → Not compliant.
- Với "clarify": Nếu AI trả lời ngay mà không hỏi lại → Not compliant."""

def behavior_compliance(inputs: dict, outputs: dict, reference_outputs: dict) -> bool:
    """Kiểm tra AI có hành xử đúng expected_behavior (answer/refuse/clarify) không."""
    grader = grader_llm.with_structured_output(BehaviorGrade, method="json_schema")
    student_answer = (outputs or {}).get("answer", "")
    verdict = (outputs or {}).get("verdict", "")

    # expected_behavior có thể nằm ở inputs HOẶC reference_outputs tùy dataset version
    expected_behavior = (
        (inputs or {}).get("expected_behavior")
        or (reference_outputs or {}).get("expected_behavior")
        or "answer"
    )

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
    return grade["compliant"]


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

Grounded = False nếu phát hiện bất kỳ số tiền hoặc điều khoản nào không có trong FACTS."""

def groundedness(inputs: dict, outputs: dict) -> bool:
    grader = grader_llm.with_structured_output(GroundednessGrade, method="json_schema")
    context = (outputs or {}).get("context", "")
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
    return grade["grounded"]


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
- Cite Điều X nhưng gắn với mức phạt của Điều Y."""

def citation_accuracy(inputs: dict, outputs: dict) -> bool:
    grader = grader_llm.with_structured_output(CitationGrade, method="json_schema")
    context = (outputs or {}).get("context", "")
    student_answer = (outputs or {}).get("answer", "")
    if not student_answer:
        return False
    prompt = f"CONTEXT:\n{context}\n\nANSWER:\n{student_answer}"
    grade = grader.invoke([
        {"role": "system", "content": CITATION_PROMPT},
        {"role": "user",   "content": prompt},
    ])
    return grade["citation_accurate"]


# ── Evaluator 5: Retrieval Node Match ────────────────────────────────────
def retrieval_node_match(inputs: dict, outputs: dict, reference_outputs: dict) -> float:
    """
    So sánh node IDs đã retrieve với reference_nodes trong dataset.

    Returns
    -------
    float : tỉ lệ hit [0.0, 1.0]
        = |retrieved ∩ reference| / |reference|
        = 1.0 nếu không có reference_nodes (không đánh giá được)
    """
    # reference_nodes nằm ở reference_outputs (LangSmith dataset) hoặc inputs (local)
    ref_nodes: list[str] = (
        (reference_outputs or {}).get("reference_nodes")
        or (inputs or {}).get("reference_nodes")
        or []
    )
    retrieved_nodes: list[str] = (outputs or {}).get("retrieved_nodes") or []

    if not ref_nodes:
        # Dataset không có reference_nodes → skip (trả 1.0 để không kéo thấp tổng)
        return 1.0

    ref_set = set(ref_nodes)
    ret_set = set(retrieved_nodes)
    hit_rate = len(ref_set & ret_set) / len(ref_set)
    return round(hit_rate, 4)