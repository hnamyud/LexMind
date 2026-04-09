"""
nodes/reflector.py
──────────────────
Step 3 — Reflector/Critic: đánh giá chất lượng context trước khi generator.

Bao gồm:
  - Constants phân loại: _PENALTY_KEYWORDS, _RETRIEVAL_MARKERS, _VEHICLE_ALIASES
  - _is_high_confidence_context : pre-check bypass LLM (keyword heuristics)
  - _node_reflector              : LLM đánh giá context với 3 verdict

Option B: _node_reflector nhận `self` (RAGService) làm tham số đầu tiên.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage

from .base import _extract_ai_text


# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

# Từ khóa cho thấy context chứa thông tin xử phạt thực sự
_PENALTY_KEYWORDS: tuple = (
    "phạt tiền", "triệu đồng", "nghìn đồng",
    "tước quyền sử dụng giấy phép", "tước bằng",
    "tạm giữ phương tiện", "tạm giữ xe",
    "trừ điểm", "điểm giấy phép lái xe",
    "cảnh cáo",
)

# Markers xuất hiện khi context thực sự đến từ graph retrieval
_RETRIEVAL_MARKERS: tuple = (
    "--- nguồn", "[multi-violation context", "vi phạm 1/",
    "nghị định 168/2024/nđ-cp", "═══",
)

# Alias loại xe để cover các cách viết khác nhau trong context
_VEHICLE_ALIASES: dict = {
    "xe máy": ["xe máy", "mô tô", "xe gắn máy", "moto"],
    "mô tô":  ["xe máy", "mô tô", "xe gắn máy", "moto"],
    "ô tô":   ["ô tô", "xe ô tô", "xe con", "xe tải", "ô tô con"],
    "xe tải": ["xe tải", "ô tô tải", "xe chở hàng"],
}


# ---------------------------------------------------------------------------
# High-confidence pre-check (pure function)
# ---------------------------------------------------------------------------

def _is_high_confidence_context(context: str, entities: dict) -> bool:
    """
    Pre-check trước khi gọi LLM reflector. Bypass khi đủ 3 điều kiện:
    1. Context có dữ liệu xử phạt (penalty keywords)
    2. Context đến từ graph retrieval (retrieval markers)
    3. Context liên quan đến đúng vi phạm và loại xe user hỏi
    """
    ctx_lower = context.lower()

    # Điều kiện 1: phải có từ khóa phạt
    if not any(kw in ctx_lower for kw in _PENALTY_KEYWORDS):
        return False

    # Điều kiện 2: phải có marker retrieval hợp lệ
    if not any(marker in ctx_lower for marker in _RETRIEVAL_MARKERS):
        return False

    # Điều kiện 3a: vi phạm phải xuất hiện trong context
    violation = entities.get("violation", "").lower()
    if violation:
        keywords = [w for w in violation.split() if len(w) > 3][:3]
        if keywords and not any(kw in ctx_lower for kw in keywords):
            logging.info(
                f"[STEP3] Pre-check fail: violation keywords {keywords} "
                f"không tìm thấy trong context → gọi LLM"
            )
            return False

    # Điều kiện 3b: vehicle_type phải khớp nếu user có chỉ định
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


# ---------------------------------------------------------------------------
# Reflector node (Option B — nhận self)
# ---------------------------------------------------------------------------

async def _node_reflector(self, state: dict) -> dict:
    """
    Step 3: LLM đánh giá context — 3 verdict:
      sufficient          → đủ thông tin, đi đến generator
      needs_clarification → có data nhưng thiếu tham số, hỏi ngược user
      not_found           → không có trong NĐ 168, chuyển sang web search

    Bổ sung: trigger_search flag
      true  → Graph data không khớp hoặc độ tin cậy thấp → force web search
      false → context đáng tin cậy

    Complexity-aware:
      Level 1 (Simple) → skip hoàn toàn, trả "sufficient"
      Level 2 (Medium) → gọi _llm_ref_l2 (thinking_budget=512)
      Level 3 (Complex)→ gọi _llm_ref_l3 (thinking_budget=1024)
    """
    complexity_level = state.get("complexity_level", 2)

    # ── Level 1: Skip Reflector hoàn toàn ──────────────────────────────
    if complexity_level == 1:
        logging.info(
            "[STEP3] SKIP Reflector (complexity_level=1 — Simple query). "
            "Trả thẳng 'sufficient' để tiết kiệm latency."
        )
        return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}

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
    entities = state.get("entities", {})

    # Pre-check: bypass LLM khi context rõ ràng đủ mạnh và đúng context
    # (Đã tắt do Pre-check chỉ kiểm tra keyword, dễ bị lọt các "vùng xám" như xe tự lái.
    # Chi phí của Gemini 3 Flash rất rẻ, nên gọi LLM Reflector 100% để đảm bảo chất lượng)
    if context and _is_high_confidence_context(context, entities):
        logging.info(
            f"[STEP3] Pre-check condition met (level={complexity_level}), nhưng đã vô hiệu hóa bypass. "
            "Vẫn gọi LLM Reflector để bắt các ca 'vùng xám' (Semantic Mismatch)."
        )
        # return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}

    prompt = self._reflector_prompt.format(
        question=question,
        context=context if context else "(Không tìm được dữ liệu từ đồ thị tri thức)",
        entities=json.dumps(entities, ensure_ascii=False, indent=2),
    )
    try:
        response = await llm_reflector.ainvoke([HumanMessage(content=prompt)])
        raw = _extract_ai_text(response).strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)
        verdict = data.get("verdict", "sufficient")
        clarification_q = data.get("clarification_question", "")
        trigger_search = data.get("trigger_search", False)

        logging.info(
            f"[STEP3] level={complexity_level}, verdict={verdict!r}, "
            f"trigger_search={trigger_search}"
        )
        return {
            "reflection": verdict,
            "clarification_question": clarification_q,
            "trigger_search": trigger_search,
        }
    except Exception as e:
        logging.error(f"[STEP3] Lỗi: {e} — fallback sufficient")
        return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}
