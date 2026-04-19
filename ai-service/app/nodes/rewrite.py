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


def _build_article_node_id(doc_ref: str, article: str, clause: str = None, point: str = None) -> str:
    """
    Build node ID từ article_ref components.
    
    Format:
    - Chỉ điều:           "l35_2024_dieu_13"
    - Điều + khoản:      "nd168_2024_d7_k7"
    - Điều + khoản + điểm: "nd168_2024_d7_k7_c"
    """
    if clause:
        parts = [doc_ref, f"d{article}", f"k{clause}"]
        if point:
            parts.append(point)
    else:
        parts = [doc_ref, f"dieu_{article}"]
    return "_".join(parts)


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
        query_mode = data.get("query_mode", "penalty_lookup")

        if query_mode == "provision_lookup":
            article_ref = entities.get("article_ref")
            document_ref = entities.get("document_ref")
            
            if article_ref and document_ref:
                article = article_ref.get("article")
                clause = article_ref.get("clause")
                point = article_ref.get("point")
                
                if article:
                    entities["article_node_id"] = _build_article_node_id(
                        document_ref, article, clause, point
                    )

        sub_queries = data.get("sub_queries", [])
        validated_subs = []
        for sq in sub_queries[:3]:
            if isinstance(sq, dict) and sq.get("legal_query"):
                validated_subs.append({
                    "legal_query": sq["legal_query"],
                    "entities": sq.get("entities", {}),
                    "label": sq.get("label", sq["legal_query"][:30]),
                })

        raw_level = data.get("complexity_level", 2)
        try:
            complexity_level = max(1, min(3, int(raw_level)))
        except (TypeError, ValueError):
            complexity_level = 2

        if len(validated_subs) >= 2 and complexity_level < 3:
            complexity_level = 3
        elif len(validated_subs) == 1 and complexity_level < 2:
            complexity_level = 2

        logging.info(
            f"[STEP1b] query_mode={query_mode}, legal_query={legal_query!r}, "
            f"sub_queries={len(validated_subs)}, complexity_level={complexity_level}"
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
            "entities": {"query_mode": "penalty_lookup"},
            "sub_queries": [],
            "complexity_level": 2,
        }
