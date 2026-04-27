"""
nodes/reflector.py
──────────────────
Step 3 — Reflector/Critic: đánh giá chất lượng context trước khi generator.

Bao gồm:
  - Constants phân loại: _PENALTY_KEYWORDS, _PROVISION_KEYWORDS, _RETRIEVAL_MARKERS
  - _is_high_confidence_penalty_context : pre-check bypass LLM cho penalty_lookup
  - _is_high_confidence_provision_context : pre-check bypass LLM cho provision_lookup
  - _node_reflector              : LLM đánh giá context với 3 verdict

Option B: _node_reflector nhận `self` (RAGService) làm tham số đầu tiên.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage

from .base import _extract_ai_text


_ALLOWED_REFLECTOR_VERDICTS = {"sufficient", "needs_clarification", "not_found"}


def _validate_reflector_payload(data: dict) -> tuple[bool, str]:
    """Strict validate payload shape/output cho reflector LLM."""
    if not isinstance(data, dict):
        return False, "payload không phải object"

    required_keys = {"verdict", "clarification_question", "trigger_search"}
    extra_keys = set(data.keys()) - required_keys
    missing_keys = required_keys - set(data.keys())

    if missing_keys:
        return False, f"thiếu keys bắt buộc: {sorted(missing_keys)}"
    if extra_keys:
        return False, f"thừa keys không cho phép: {sorted(extra_keys)}"

    verdict = data.get("verdict")
    if verdict not in _ALLOWED_REFLECTOR_VERDICTS:
        return False, f"verdict không hợp lệ: {verdict!r}"

    clarification_question = data.get("clarification_question")
    if not isinstance(clarification_question, str):
        return False, "clarification_question phải là string"

    trigger_search = data.get("trigger_search")
    if not isinstance(trigger_search, bool):
        return False, "trigger_search phải là boolean"

    if verdict != "needs_clarification" and clarification_question.strip():
        return False, "clarification_question phải rỗng khi verdict != needs_clarification"

    return True, ""


# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

# Từ khóa cho thấy context chứa thông tin xử phạt thực sự (penalty_lookup)
_PENALTY_KEYWORDS: tuple = (
    "phạt tiền",
    "triệu đồng",
    "nghìn đồng",
    "tước quyền sử dụng giấy phép",
    "tước bằng",
    "tạm giữ phương tiện",
    "tạm giữ xe",
    "trừ điểm",
    "điểm giấy phép lái xe",
    "cảnh cáo",
)

# Từ khóa cho thấy context chứa thông tin quy định/định nghĩa (provision_lookup)
_PROVISION_KEYWORDS: tuple = (
    "là",
    "gồm",
    "bao gồm",
    "được hiểu là",
    "được quy định",
    "nguyên tắc",
    "quy định",
    "theo quy định",
    "có nghĩa là",
)

# Markers xuất hiện khi context thực sự đến từ graph retrieval (XML format)
_RETRIEVAL_MARKERS: tuple = (
    "<source ",
    "<multi_violation",
    "nghị định 168/2024/nđ-cp",
    "luật đường bộ",
    "luật trật tự",
)

# Alias loại xe để cover các cách viết khác nhau trong context
_VEHICLE_ALIASES: dict = {
    "xe máy": ["xe máy", "mô tô", "xe gắn máy", "moto"],
    "mô tô": ["xe máy", "mô tô", "xe gắn máy", "moto"],
    "ô tô": ["ô tô", "xe ô tô", "xe con", "xe tải", "ô tô con"],
    "xe tải": ["xe tải", "ô tô tải", "xe chở hàng"],
}


# ---------------------------------------------------------------------------
# High-confidence pre-check functions
# ---------------------------------------------------------------------------


def _is_high_confidence_penalty_context(context: str, entities: dict) -> bool:
    """
    Pre-check cho penalty_lookup mode. Bypass khi đủ 3 điều kiện:
    1. Context có dữ liệu xử phạt (penalty keywords)
    2. Context đến từ graph retrieval (retrieval markers)
    3. Context liên quan đến đúng vi phạm và loại xe user hỏi
    """
    ctx_lower = context.lower()

    if not any(kw in ctx_lower for kw in _PENALTY_KEYWORDS):
        return False

    if not any(marker in ctx_lower for marker in _RETRIEVAL_MARKERS):
        return False

    violation = entities.get("violation", "").lower()
    if violation:
        keywords = [w for w in violation.split() if len(w) > 3][:3]
        if keywords and not any(kw in ctx_lower for kw in keywords):
            logging.info(
                f"[STEP3] Pre-check fail: violation keywords {keywords} "
                f"không tìm thấy trong context → gọi LLM"
            )
            return False

    vehicle_type = entities.get("vehicle_type", "").lower()
    if vehicle_type:
        aliases = _VEHICLE_ALIASES.get(vehicle_type, [vehicle_type])
        if not any(alias in ctx_lower for alias in aliases):
            logging.info(
                f"[STEP3] Pre-check fail: vehicle_type='{vehicle_type}' "
                f"không tìm thấy trong context → gọi LLM"
            )
            return False

    return True


def _is_high_confidence_provision_context(context: str, entities: dict) -> bool:
    """
    Pre-check cho provision_lookup mode. Bypass khi đủ điều kiện:
    1. Context có marker retrieval hợp lệ
    2. Context có từ khóa quy định/định nghĩa
    3. Nếu có legal_concept, nó xuất hiện trong context
    4. Nếu có document_ref, doc_ref khớp trong context
    """
    ctx_lower = context.lower()

    if not any(marker in ctx_lower for marker in _RETRIEVAL_MARKERS):
        return False

    if not any(kw in ctx_lower for kw in _PROVISION_KEYWORDS):
        return False

    legal_concept = entities.get("legal_concept", "").lower()
    if legal_concept:
        concept_words = [w for w in legal_concept.split() if len(w) > 2][:3]
        if concept_words and not any(w in ctx_lower for w in concept_words):
            logging.info(
                f"[STEP3] Pre-check fail: legal_concept words {concept_words} "
                f"không tìm thấy trong context → gọi LLM"
            )
            return False

    document_ref = entities.get("document_ref", "")
    if document_ref:
        if document_ref not in context:
            logging.info(
                f"[STEP3] Pre-check fail: document_ref='{document_ref}' "
                f"không tìm thấy trong context → gọi LLM"
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Reflector node (Option B — nhận self)
# ---------------------------------------------------------------------------


async def _node_reflector(self, state: dict) -> dict:
    """
    Step 3: LLM đánh giá context — 3 verdict:
      sufficient          → đủ thông tin, đi đến generator
      needs_clarification → có data nhưng thiếu tham số, hỏi ngược user
      not_found           → không có trong văn bản luật, chuyển sang web search

    Bổ sung: trigger_search flag
      true  → Graph data không khớp hoặc độ tin cậy thấp → force web search
      false → context đáng tin cậy

    Query-mode aware:
      - penalty_lookup → check penalty keywords
      - provision_lookup → check provision keywords + doc_ref

    Complexity-aware:
      Level 1 (Simple) → skip hoàn toàn, trả "sufficient"
      Level 2 (Medium) → gọi _llm_ref_l2 (thinking_budget=512)
      Level 3 (Complex)→ gọi _llm_ref_l3 (thinking_budget=1024)
    """
    complexity_level = state.get("complexity_level", 2)
    entities = state.get("entities", {})
    query_mode = entities.get("query_mode", "penalty_lookup")

    # ── Level 1: Skip Reflector hoàn toàn ──────────────────────────────
    if complexity_level == 1:
        logging.info(
            f"[STEP3] SKIP Reflector (complexity_level=1 — Simple query, mode={query_mode}). "
            "Trả thẳng 'sufficient' để tiết kiệm latency."
        )
        return {
            "reflection": "sufficient",
            "clarification_question": "",
            "trigger_search": False,
        }

    # ── Level 2/3: Chọn LLM theo level ─────────────────────────────────
    _llm_map = {
        2: self._llm_ref_l2,  # thinking_budget=512
        3: self._llm_ref_l3,  # thinking_budget=1024
    }
    llm_reflector = _llm_map.get(complexity_level, self._llm_ref_l2)

    messages = state.get("messages", [])
    question = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            question = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    context = state.get("context", "")

    # Pre-check theo query_mode
    if context:
        if query_mode == "provision_lookup":
            if _is_high_confidence_provision_context(context, entities):
                logging.info(
                    f"[STEP3] Pre-check passed for provision_lookup (level={complexity_level}). "
                    "Context có đủ thông tin quy định/định nghĩa."
                )
        else:
            if _is_high_confidence_penalty_context(context, entities):
                logging.info(
                    f"[STEP3] Pre-check condition met for penalty_lookup (level={complexity_level}), nhưng đã vô hiệu hóa bypass. "
                    "Vẫn gọi LLM Reflector để bắt các ca 'vùng xám' (Semantic Mismatch)."
                )

    question_text = question
    context_text = context if context else "(Không tìm được dữ liệu từ đồ thị tri thức)"
    entities_text = json.dumps(entities, ensure_ascii=False, indent=2)

    prompt = (
        self._reflector_prompt
        .replace("{question}", question_text)
        .replace("{context}", context_text)
        .replace("{entities}", entities_text)
    )
    try:
        response = await llm_reflector.ainvoke([HumanMessage(content=prompt)])
        raw = _extract_ai_text(response).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())
        data = json.loads(raw)
        is_valid, reason = _validate_reflector_payload(data)
        if not is_valid:
            raise ValueError(f"reflector payload invalid: {reason}")

        verdict = data.get("verdict", "sufficient")
        clarification_q = data.get("clarification_question", "")
        trigger_search = data.get("trigger_search", False)

        logging.info(
            f"[STEP3] level={complexity_level}, mode={query_mode}, verdict={verdict!r}, "
            f"trigger_search={trigger_search}"
        )
        return {
            "reflection": verdict,
            "clarification_question": clarification_q,
            "trigger_search": trigger_search,
        }
    except Exception as e:
        logging.error(f"[STEP3] Lỗi: {e} — fallback sufficient")
        return {
            "reflection": "sufficient",
            "clarification_question": "",
            "trigger_search": False,
        }
