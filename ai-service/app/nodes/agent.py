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

from langchain_core.messages import AIMessage, SystemMessage


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

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    recent_chat_msgs = chat_msgs[-8:]

    messages_to_llm = system_msgs + recent_chat_msgs

    # Agent Direct luôn dùng natural prompt (thân thiện)
    if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
        messages_to_llm = [SystemMessage(content=self._natural_prompt)] + messages_to_llm

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
    return {"messages": [AIMessage(content=clarification_q)]}
