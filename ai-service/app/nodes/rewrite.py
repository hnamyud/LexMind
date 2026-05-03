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


_ALLOWED_QUERY_MODES = {"penalty_lookup", "provision_lookup"}
_ALLOWED_DOCUMENT_REFS = {"nd168_2024", "l35_2024", "l36_2024"}

_FOLLOWUP_PATTERNS: tuple[str, ...] = (
    r"\bcòn\b",
    r"\bthế\b",
    r"\bvậy\b",
    r"\bthì sao\b",
    r"\bcái này\b",
    r"\bcái đó\b",
    r"\btrường hợp đó\b",
    r"\bnhư trên\b",
    r"\btương tự\b",
    r"\bnữa\b",
)


def _validate_rewrite_payload(data: dict) -> tuple[bool, str]:
    """Strict validate payload shape/output cho rewrite LLM."""
    if not isinstance(data, dict):
        return False, "payload không phải object"

    required_keys = {
        "query_mode",
        "legal_query",
        "entities",
        "sub_queries",
        "complexity_level",
        "standalone_question",
    }
    extra_keys = set(data.keys()) - required_keys
    missing_keys = required_keys - set(data.keys())
    if missing_keys:
        return False, f"thiếu keys bắt buộc: {sorted(missing_keys)}"
    if extra_keys:
        return False, f"thừa keys không cho phép: {sorted(extra_keys)}"

    query_mode = data.get("query_mode")
    if query_mode not in _ALLOWED_QUERY_MODES:
        return False, f"query_mode không hợp lệ: {query_mode!r}"

    legal_query = data.get("legal_query")
    if legal_query is not None and not isinstance(legal_query, str):
        return False, "legal_query phải là string hoặc null"

    entities = data.get("entities")
    if not isinstance(entities, dict):
        return False, "entities phải là object"

    sub_queries = data.get("sub_queries")
    if not isinstance(sub_queries, list):
        return False, "sub_queries phải là list"

    complexity_level = data.get("complexity_level")
    if not isinstance(complexity_level, int) or complexity_level not in (1, 2, 3):
        return False, f"complexity_level không hợp lệ: {complexity_level!r}"

    standalone_question = data.get("standalone_question")
    if not isinstance(standalone_question, bool):
        return False, f"standalone_question không hợp lệ: {standalone_question!r}"

    if query_mode == "penalty_lookup":
        allowed_entity_keys = {"violation", "vehicle_type", "subject", "conditions"}
        extra_entity_keys = set(entities.keys()) - allowed_entity_keys
        if extra_entity_keys:
            return False, f"entities penalty thừa keys: {sorted(extra_entity_keys)}"

        if entities.get("violation") is not None and not isinstance(entities.get("violation"), str):
            return False, "entities.violation phải là string hoặc null"
        if entities.get("vehicle_type") is not None and not isinstance(entities.get("vehicle_type"), str):
            return False, "entities.vehicle_type phải là string hoặc null"
        if entities.get("subject") is not None and not isinstance(entities.get("subject"), str):
            return False, "entities.subject phải là string hoặc null"
        if entities.get("conditions") is not None and not isinstance(entities.get("conditions"), list):
            return False, "entities.conditions phải là list hoặc null"

    if query_mode == "provision_lookup":
        allowed_entity_keys = {"legal_concept", "document_ref", "article_ref"}
        extra_entity_keys = set(entities.keys()) - allowed_entity_keys
        if extra_entity_keys:
            return False, f"entities provision thừa keys: {sorted(extra_entity_keys)}"

        legal_concept = entities.get("legal_concept")
        if legal_concept is not None and not isinstance(legal_concept, str):
            return False, "entities.legal_concept phải là string hoặc null"

        document_ref = entities.get("document_ref")
        if document_ref is not None:
            if not isinstance(document_ref, str):
                return False, "entities.document_ref phải là string hoặc null"
            if document_ref not in _ALLOWED_DOCUMENT_REFS:
                return False, f"entities.document_ref không hợp lệ: {document_ref!r}"

        article_ref = entities.get("article_ref")
        if article_ref is not None:
            if not isinstance(article_ref, dict):
                return False, "entities.article_ref phải là object hoặc null"
            article_keys = set(article_ref.keys())
            if article_keys != {"article", "clause", "point"}:
                return False, "entities.article_ref phải có đúng keys: article, clause, point"
            if not isinstance(article_ref.get("article"), str):
                return False, "entities.article_ref.article phải là string"
            if article_ref.get("clause") is not None and not isinstance(article_ref.get("clause"), str):
                return False, "entities.article_ref.clause phải là string hoặc null"
            if article_ref.get("point") is not None and not isinstance(article_ref.get("point"), str):
                return False, "entities.article_ref.point phải là string hoặc null"

    return True, ""


def _is_standalone_question(question: str) -> bool:
    """
    Heuristic xác định câu hỏi độc lập hay follow-up theo ngữ cảnh trước đó.
    - Có marker follow-up ngắn/generic -> không standalone.
    - Có tham chiếu pháp lý rõ ràng -> standalone.
    """
    q = (question or "").strip().lower()
    if not q:
        return False

    # Có tham chiếu pháp lý tương đối đầy đủ -> coi như độc lập
    if re.search(r"\b(điều\s*\d+|khoản\s*\d+|điểm\s*[a-zđ]|luật|nghị định|mức phạt|phạt bao nhiêu)\b", q):
        return True

    # Câu ngắn + có marker follow-up -> nhiều khả năng phụ thuộc ngữ cảnh trước
    if len(q) <= 120 and any(re.search(p, q, re.IGNORECASE) for p in _FOLLOWUP_PATTERNS):
        return False

    return True


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
        is_valid, reason = _validate_rewrite_payload(data)
        if not is_valid:
            raise ValueError(f"rewrite payload invalid: {reason}")

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

        standalone_question = data.get("standalone_question")

        logging.info(
            f"[STEP1b] query_mode={query_mode}, legal_query={legal_query!r}, "
            f"sub_queries={len(validated_subs)}, complexity_level={complexity_level}, "
            f"standalone_question={standalone_question}"
        )
        entities["query_mode"] = query_mode

        return {
            "legal_query": legal_query,
            "entities": entities,
            "sub_queries": validated_subs,
            "complexity_level": complexity_level,
            "standalone_question": standalone_question,
        }
    except Exception as e:
        logging.error(f"[STEP1b] Lỗi: {e} — fallback")
        return {
            "legal_query": last_question,
            "entities": {"query_mode": "penalty_lookup"},
            "sub_queries": [],
            "complexity_level": 2,
            "standalone_question": _is_standalone_question(last_question),
        }
