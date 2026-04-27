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
import re

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage


_META_SYSTEM_QUERY_PATTERNS: tuple[str, ...] = (
    r"\b(prompt|system prompt|developer prompt|hidden prompt)\b",
    r"\b(chain[ -]?of[ -]?thought|cot|reasoning)\b",
    r"\b(quy tắc bắt buộc|nguyên tắc nội bộ|cơ chế nội bộ|luật nội bộ)\b",
    r"\b(audit nội bộ|kiểm thử bảo mật|security audit|pentest)\b",
    r"\b(nguyên tắc bạn tuân theo|quy tắc của bạn|chính sách nội bộ)\b",
    r"\b(bạn bị cấm làm gì|nguyên tắc ẩn|hướng dẫn nội bộ)\b",
    r"\b(in ra|show|dump|xuất ra).*(prompt|rule|quy tắc|hướng dẫn)\b",
    r"\b(liệt kê|mô tả|cho biết).*(quy tắc|nguyên tắc|cơ chế|policy)\b",
    r"\b(bỏ qua|ignore).*(hướng dẫn|instructions|system)\b",
)


def _is_meta_or_injection_query(text: str) -> bool:
    q = (text or "").lower()
    if not q:
        return False
    return any(re.search(p, q, re.IGNORECASE) for p in _META_SYSTEM_QUERY_PATTERNS)


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
    if _is_meta_or_injection_query(last_user):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "Mình không thể cung cấp hoặc mô tả các quy tắc nội bộ, "
                        "cơ chế bảo mật, hay hướng dẫn vận hành của hệ thống. "
                        "Nếu bạn muốn, mình có thể hỗ trợ câu hỏi pháp lý giao thông cụ thể."
                    )
                )
            ]
        }

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    recent_chat_msgs = chat_msgs[-4:]

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
