"""
nodes/generator.py
──────────────────
Step 4 — Generator: tổng hợp câu trả lời cuối dựa trên context từ retriever/web.

Option B: hàm nhận `self` (RAGService instance) làm tham số đầu tiên.
"""

import logging
import re

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


_INJECTION_PATTERNS: tuple[str, ...] = (
    r"\bignore\s+previous\s+instructions\b",
    r"\bsystem\s*:\b",
    r"\bdeveloper\s*:\b",
    r"\bact\s+as\b",
    r"\breveal\s+(?:hidden\s+)?prompt\b",
    r"\bchain[ -]?of[ -]?thought\b",
    r"\bbỏ qua\s+hướng dẫn\b",
    r"\bin ra\s+.*(?:quy tắc|prompt|hướng dẫn)\b",
)


def _looks_like_injection(text: str) -> bool:
    q = (text or "").lower()
    if not q:
        return False
    return any(re.search(p, q, re.IGNORECASE) for p in _INJECTION_PATTERNS)


async def _node_generator(self, state: dict) -> dict:
    """
    Step 4: Tổng hợp câu trả lời cuối cùng.
    Context (từ Neo4j hoặc web) được inject vào messages trước khi gọi LLM.

    response_style từ Router quyết định giọng văn:
      - "legal"   → format Terminal cứng, trích dẫn pháp lý nghiêm túc
      - "natural"  → trả lời như một người bạn thân thiện

    Complexity-aware (thinking_budget):
      - Level 1 (Simple):  thinking_level=low  (tắt thinking)
      - Level 2 (Medium):  thinking_level=medium
      - Level 3 (Complex): thinking_level=high
    """
    complexity_level = state.get("complexity_level", 2)
    _llm_gen_map = {
        1: self._llm_gen_l1,  # thinking_level=low
        2: self._llm_gen_l2,  # thinking_level=medium
        3: self._llm_gen_l3,  # thinking_level=high
    }
    llm = _llm_gen_map.get(complexity_level, self._llm_gen_l2)
    _model_name = getattr(llm, "model", None) or getattr(llm, "model_name", "unknown")
    logging.info(f"[STEP4] Generator L{complexity_level} → model={_model_name!r}")

    messages = list(state.get("messages", []))
    context = state.get("context", "")
    style = state.get("response_style", "legal")
    standalone_question = bool(state.get("standalone_question", False))

    # Hard safety guard: nếu user gửi chuỗi dạng injection probing,
    # trả lời từ chối ngắn gọn, không đi vào LLM để tránh khuếch đại chuỗi độc hại.
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user = m.content if isinstance(m.content, str) else str(m.content)
            break
    if _looks_like_injection(last_user):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Mình không thể hỗ trợ các yêu cầu can thiệp cơ chế nội bộ hoặc thay đổi chỉ dẫn hệ thống. "
                        "Nếu bạn muốn, mình có thể hỗ trợ câu hỏi pháp lý giao thông cụ thể."
                    )
                )
            ]
        }
    entities = state.get("entities") or {}
    query_mode = entities.get("query_mode", "penalty_lookup")

    # 1. Tách SystemMessage cũ ra khỏi tin nhắn User/AI để không bị cắt xoá
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

    # 2. Lấy lịch sử chat theo cờ standalone_question
    # - standalone=True  -> chỉ giữ câu hỏi user mới nhất, tránh kéo ngữ cảnh cũ
    # - standalone=False -> giữ 4 tin gần nhất như cũ
    if standalone_question:
        latest_human_msg = None
        for m in reversed(chat_msgs):
            if isinstance(m, HumanMessage):
                latest_human_msg = m
                break
        recent_chat_msgs = [latest_human_msg] if latest_human_msg else chat_msgs[-1:]
    else:
        recent_chat_msgs = chat_msgs[-4:]

    # 3. Chọn system prompt theo response_style + query_mode + độ phức tạp
    # Chỉ dùng compact cho penalty_lookup đơn giản.
    # provision_lookup luôn dùng prompt đầy đủ để giữ citation ổn định.
    is_single_violation = len(state.get("sub_queries", [])) == 0
    if (
        style == "legal"
        and query_mode == "penalty_lookup"
        and complexity_level == 1
        and is_single_violation
    ):
        chosen_prompt = self._system_prompt_compact
    elif style == "legal":
        chosen_prompt = self._system_prompt
    else:
        chosen_prompt = self._natural_prompt

    # Inject query_mode an toàn bằng replace (không dùng format)
    # để tránh KeyError với các literal như {doc_ref} trong prompt text.
    if "{query_mode}" in chosen_prompt:
        chosen_prompt = chosen_prompt.replace("{query_mode}", str(query_mode or "penalty_lookup"))

    # 4. Ghép lại danh sách messages cho LLM
    messages_to_llm = system_msgs + recent_chat_msgs

    if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
        messages_to_llm = [SystemMessage(content=chosen_prompt)] + messages_to_llm

    if context:
        messages_to_llm = messages_to_llm + [
            SystemMessage(
                content=(
                    "<retrieved_context>\n"
                    "  <instructions>\n"
                    "    <rule>Mỗi tag &lt;source&gt; chứa một anchor duy nhất. Chỉ trích dẫn số Điều/Khoản nếu nó xuất hiện TƯỜNG MINH trong thuộc tính id của tag đó.</rule>\n"
                    "    <rule>TUYỆT ĐỐI KHÔNG ghép số Điều từ source này với mức phạt từ source khác.</rule>\n"
                    "    <rule>TUYỆT ĐỐI KHÔNG dùng kiến thức ngoài context để suy ra số Điều/Khoản.</rule>\n"
                    "    <rule>Nếu không tìm thấy điều/khoản rõ ràng trong id, chỉ mô tả mức phạt, không ghi số Điều/Khoản.</rule>\n"
                    "    <rule>Nếu context là &lt;multi_violation&gt;: mỗi &lt;violation&gt; là nguồn dữ liệu riêng biệt. Xử lý từng phần và tổng hợp cộng dồn cuối cùng.</rule>\n"
                    "  </instructions>\n"
                    "  <sources>\n"
                    f"{context}\n"
                    "  </sources>\n"
                    "</retrieved_context>"
                )
            )
        ]

    # Inject skill 02 + 03 cho legal flow để bổ sung hướng dẫn đọc graph và kiểm toán trích dẫn
    if style == "legal":
        skill_parts = [
            s for s in [self._skill_graph_analyzer, self._skill_citation_validator] if s
        ]
        if skill_parts:
            messages_to_llm = messages_to_llm + [
                SystemMessage(content="\n\n---\n\n".join(skill_parts))
            ]

    try:
        response = await llm.ainvoke(messages_to_llm)
        return {"messages": [response]}
    except Exception as e:
        logging.error(f"[STEP4] Lỗi: {e}")
        return {
            "messages": [
                AIMessage(content=f"Xin lỗi, đã xảy ra lỗi khi soạn câu trả lời: {e}")
            ]
        }
