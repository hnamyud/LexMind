"""
nodes/agent.py
──────────────
Agent nodes (non-RAG flows):
  - _node_agent_direct : trả lời câu hỏi direct_answer với streaming thật sự
  - _node_agent_reject : từ chối câu hỏi out_of_domain
  - _node_clarifier    : hỏi ngược user khi context thiếu tham số điều kiện

Option B: tất cả hàm nhận `self` (RAGService) làm tham số đầu tiên.

Streaming note:
  _node_agent_direct dùng _llm_direct (LLM_DIRECT, streaming=True).
  LangGraph sẽ phát on_chat_model_stream events → streaming.py handle token-by-token.
  Node return AIMessage đầy đủ để LangGraph lưu vào state (checkpointer).
"""

import logging

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from .safety import is_meta_or_injection_query, generic_refusal_message


async def _node_agent_direct(self, state: dict) -> dict:
    """
    Trả lời trực tiếp cho câu hỏi direct_answer (chào hỏi, hỏi về chatbot, v.v.)
    Luôn dùng style "natural" — giọng văn thân thiện.

    Dùng _llm_direct (LLM_DIRECT, streaming=True):
      - Model riêng → không tranh tài nguyên với router
      - streaming=True → LangGraph phát on_chat_model_stream → frontend nhận token ngay
      - temperature=0.7 → câu trả lời tự nhiên, không cứng nhắc
    """
    messages = list(state.get("messages", []))

    # Defense-in-depth: chặn truy vấn probe cơ chế nội bộ/prompt injection
    # ngay cả khi router classify miss.
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user = m.content if isinstance(m.content, str) else str(m.content)
            break
    if is_meta_or_injection_query(last_user):
        return {"messages": [AIMessage(content=generic_refusal_message())]}

    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    recent_chat_msgs = chat_msgs[-4:]

    # Không forward SystemMessage cũ từ history để tránh leak nội bộ.
    messages_to_llm = [SystemMessage(content=self._natural_prompt)] + recent_chat_msgs

    try:
        # ainvoke với streaming=True: LangGraph tự phát on_chat_model_stream
        # streaming.py lắng nghe event này để yield token về frontend
        response = await self._llm_direct.ainvoke(messages_to_llm)
        return {"messages": [response]}
    except Exception as e:
        logging.error(f"[DIRECT] Lỗi: {e}")
        return {"messages": [AIMessage(content=f"Xin lỗi, đã xảy ra lỗi: {e}")]}


async def _node_agent_reject(self, state: dict) -> dict:
    """Trả lời từ chối cho câu hỏi out_of_domain, sử dụng lý do từ router (legal_query)."""
    legal_query = state.get("legal_query", "")
    reason = (
        legal_query.replace("REJECT:", "").strip()
        if "REJECT:" in legal_query
        else "Xin lỗi, tôi chỉ tư vấn các vấn đề nằm trong phạm vi Luật Giao thông (Nghị định 168/2024/NĐ-CP)."
    )
    if not reason:
        reason = "Xin lỗi, tôi chỉ tư vấn các vấn đề nằm trong phạm vi Luật Giao thông (Nghị định 168/2024/NĐ-CP)."
    return {"messages": [AIMessage(content=reason)]}


async def _node_clarifier(self, state: dict) -> dict:
    """Step 3b: Hỏi ngược user khi context có data nhưng thiếu tham số điều kiện."""
    clarification_q = state.get(
        "clarification_question",
        "Bạn có thể cung cấp thêm thông tin để tôi tư vấn chính xác hơn không?",
    )
    return {
        "messages": [AIMessage(content=clarification_q)],
        "awaiting_clarification": True,
        "clarification_kind": "confirm_interpretation",
        "clarification_payload": {
            "resolved_question_text": state.get("legal_query", "").strip(),
            "resolved_entities": state.get("entities", {}) or {},
        },
    }
