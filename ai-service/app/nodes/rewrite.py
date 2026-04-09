"""
nodes/rewrite.py
────────────────
Step 1b — Rewrite: chuẩn hóa thuật ngữ + bóc tách entities +
phân tách đa vi phạm + đánh giá complexity.
Chỉ được gọi khi route == "use_tool".

Option B: hàm nhận `self` (RAGService instance) làm tham số đầu tiên.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .base import _extract_ai_text


async def _node_rewrite(self, state: dict) -> dict:
    """
    Step 1b: Chuẩn hóa thuật ngữ + bóc tách entities + phân tách đa vi phạm + đánh giá complexity.
    Chỉ được gọi khi route == "use_tool" (router đã xác nhận là câu hỏi pháp lý).
    """
    messages = list(state.get("messages", []))

    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    recent_msgs = chat_msgs[-4:]

    last_question = ""
    for m in reversed(recent_msgs):
        if isinstance(m, HumanMessage):
            last_question = m.content if isinstance(m.content, str) else str(m.content)
            break

    if not last_question:
        return {
            "legal_query": "",
            "entities": {},
            "sub_queries": [],
            "complexity_level": 2,
        }

    def _fmt_msg(m) -> str:
        role = "User" if isinstance(m, HumanMessage) else "AI"
        text = m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, AIMessage) and len(text) > 300:
            text = text[:300] + "...[rút gọn]"
        return f"{role}: {text}"

    history_text = "\n".join([_fmt_msg(m) for m in recent_msgs])
    question = f"--- Lịch sử chat gần đây ---\n{history_text}\n--- Câu hỏi hiện tại ---\nUser: {last_question}"

    prompt = self._rewrite_prompt.format(question=question)
    try:
        response = await self._llm_router.ainvoke([HumanMessage(content=prompt)])
        raw = _extract_ai_text(response).strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)

        legal_query = data.get("legal_query", "")
        entities = data.get("entities", {})

        # Parse & validate sub_queries
        sub_queries = data.get("sub_queries", [])
        validated_subs = []
        for sq in sub_queries[:3]:
            if isinstance(sq, dict) and sq.get("legal_query"):
                validated_subs.append({
                    "legal_query": sq["legal_query"],
                    "entities": sq.get("entities", {}),
                    "label": sq.get("label", sq["legal_query"][:30]),
                })

        # Parse + validate complexity_level
        raw_level = data.get("complexity_level", 2)
        try:
            complexity_level = max(1, min(3, int(raw_level)))
        except (TypeError, ValueError):
            complexity_level = 2

        # Auto-upgrade dựa trên số sub_queries
        if len(validated_subs) >= 2 and complexity_level < 3:
            complexity_level = 3
        elif len(validated_subs) == 1 and complexity_level < 2:
            complexity_level = 2

        logging.info(
            f"[STEP1b] legal_query={legal_query!r}, sub_queries={len(validated_subs)}, "
            f"complexity_level={complexity_level}"
        )
        return {
            "legal_query": legal_query,
            "entities": entities,
            "sub_queries": validated_subs,
            "complexity_level": complexity_level,
        }
    except Exception as e:
        logging.error(f"[STEP1b] Lỗi: {e} — fallback")
        return {
            "legal_query": last_question,
            "entities": {},
            "sub_queries": [],
            "complexity_level": 2,
        }
