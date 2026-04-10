"""
nodes/generator.py
──────────────────
Step 4 — Generator: tổng hợp câu trả lời cuối dựa trên context từ retriever/web.

Option B: hàm nhận `self` (RAGService instance) làm tham số đầu tiên.
"""

import logging

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


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
    logging.info(
        f"[STEP4] Generator L{complexity_level} → model={_model_name!r}"
    )

    messages = list(state.get("messages", []))
    context = state.get("context", "")
    style = state.get("response_style", "legal")

    # 1. Tách SystemMessage cũ ra khỏi tin nhắn User/AI để không bị cắt xoá
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

    # 2. Giữ 4 tin nhắn lịch sử gần nhất (2 lượt chat)
    recent_chat_msgs = chat_msgs[-4:]

    # 3. Chọn system prompt theo response_style + độ phức tạp
    # level 1 + single violation => dùng prompt rút gọn để trả lời nhanh cho 1 hành vi
    is_single_violation = len(state.get("sub_queries", [])) == 0
    if style == "legal" and complexity_level == 1 and is_single_violation:
        chosen_prompt = self._system_prompt_compact
    elif style == "legal":
        chosen_prompt = self._system_prompt
    else:
        chosen_prompt = self._natural_prompt

    # 4. Ghép lại danh sách messages cho LLM
    messages_to_llm = system_msgs + recent_chat_msgs

    if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
        messages_to_llm = [SystemMessage(content=chosen_prompt)] + messages_to_llm

    if context:
        messages_to_llm = messages_to_llm + [
            SystemMessage(
                content=(
                    "[RETRIEVED_CONTEXT]\n"
                    f"{context}\n"
                    "[/RETRIEVED_CONTEXT]\n\n"
                    "HƯỚNG DẪN SỬ DỤNG CONTEXT:\n"
                    "1. Mỗi block bắt đầu bằng '═══ [Điều X, Khoản Y...] ═══' là một anchor duy nhất.\n"
                    "   → Chỉ trích dẫn số Điều/Khoản nếu nó xuất hiện TƯỜNG MINH trong header '═══' đó.\n"
                    "2. TUYỆT ĐỐI KHÔNG ghép số Điều từ block này với mức phạt từ block khác.\n"
                    "3. TUYỆT ĐỐI KHÔNG dùng kiến thức ngoài context để suy ra số Điều/Khoản.\n"
                    "4. Nếu không tìm thấy header '═══' → không ghi Điều/Khoản, chỉ mô tả mức phạt.\n"
                    "5. Nếu context bắt đầu bằng '[MULTI-VIOLATION CONTEXT]': mỗi phần 'VI PHẠM X' "
                    "là nguồn dữ liệu riêng biệt. Xử lý từng phần và tổng hợp cộng dồn cuối cùng.\n"
                )
            )
        ]

    # Inject skill 02 + 03 cho legal flow để bổ sung hướng dẫn đọc graph và kiểm toán trích dẫn
    if style == "legal":
        skill_parts = [
            s for s in [self._skill_graph_analyzer, self._skill_citation_validator]
            if s
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
        return {"messages": [AIMessage(content=f"Xin lỗi, đã xảy ra lỗi khi soạn câu trả lời: {e}")]}
