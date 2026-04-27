"""
nodes/router.py
───────────────
Step 1a — Router: phân loại nhanh câu hỏi vào 4 nhóm:
    - use_tool       → câu hỏi pháp lý → đi _node_rewrite
    - direct_answer  → chào hỏi, hỏi về chatbot → đi thẳng agent_direct
    - absurd_logic   → tình huống phi logic/không phải vi phạm → đi agent_direct (natural)
    - out_of_domain  → ngoài phạm vi → đi agent_reject

Option B: hàm nhận `self` (RAGService instance) làm tham số đầu tiên.
RAGService sẽ bind: self._node_router = types.MethodType(_node_router, self)
"""

import asyncio
import json
import logging
import re

from langchain_core.runnables.config import RunnableConfig
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .base import _extract_ai_text


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


async def _node_router(self, state: dict, config: RunnableConfig | None = None) -> dict:
    """
        Step 1a: Phân loại câu hỏi vào 4 nhóm:
      - use_tool       → câu hỏi luật giao thông → đi _node_rewrite
      - direct_answer  → chào hỏi, hỏi về chatbot → đi thẳng agent_direct
            - absurd_logic   → tình huống phi logic/không phải vi phạm → đi agent_direct
      - out_of_domain  → ngoài phạm vi → đi agent_reject

    Dùng _llm_router và prompt cực ngắn — không rewrite, không extract entities.
    """
    enable_web_search = True
    enable_cache = True
    if config and "configurable" in config:
        enable_web_search = config["configurable"].get("enable_web_search", True)
        enable_cache = config["configurable"].get("enable_cache", True)
    logging.info(f"[STEP1] enable_web_search={enable_web_search}")
    logging.info(f"[STEP1] enable_cache={enable_cache}")

    messages = list(state.get("messages", []))
    chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    # Chỉ lấy 4 messages gần nhất — router chỉ cần đủ ngữ cảnh phân loại
    recent_msgs = chat_msgs[-4:]

    if not recent_msgs:
        return {
            "route": "direct_answer",
            "response_style": "natural",
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
        }

    last_question = ""
    for m in reversed(recent_msgs):
        if isinstance(m, HumanMessage):
            last_question = m.content if isinstance(m.content, str) else str(m.content)
            break

    if not last_question:
        return {
            "route": "direct_answer",
            "response_style": "natural",
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
        }

    # Hard block: chặn truy vấn cơ chế nội bộ/prompt injection probing
    # để tránh đi sâu vào generator và bị partial leak.
    if _is_meta_or_injection_query(last_question):
        logging.warning("[STEP1a] Meta/injection probing detected — force out_of_domain")
        return {
            "route": "out_of_domain",
            "response_style": "natural",
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
            "legal_query": "",
            "entities": {},
            "sub_queries": [],
            "complexity_level": 1,
        }

    # Truncate AI responses dài để giữ prompt nhỏ
    def _fmt_msg(m) -> str:
        role = "User" if isinstance(m, HumanMessage) else "AI"
        text = m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, AIMessage) and len(text) > 300:
            text = text[:300] + "...[rút gọn]"
        return f"{role}: {text}"

    history_text = "\n".join([_fmt_msg(m) for m in recent_msgs])
    question = f"--- Lịch sử chat gần đây ---\n{history_text}\n--- Câu hỏi hiện tại ---\nUser: {last_question}"

    # Avoid str.format() here because prompt templates include JSON examples
    # (e.g. {"route": ...}) that can accidentally trigger KeyError.
    prompt = self._router_classify_prompt.replace("{question}", question)

    # Hard timeout: align với LLM timeout=25s + 5s buffer
    # LLM timeout fires first với proper error → asyncio.TimeoutError là last resort
    _ROUTER_TIMEOUT = 30.0

    try:
        response = await asyncio.wait_for(
            self._llm_router.ainvoke([HumanMessage(content=prompt)]),
            timeout=_ROUTER_TIMEOUT,
        )
        raw = _extract_ai_text(response).strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)
        allowed_routes = {"use_tool", "direct_answer", "absurd_logic", "out_of_domain"}

        # Output validation (strict): chỉ chấp nhận JSON có đúng 1 field `route`
        # và giá trị phải nằm trong enum cho phép.
        is_valid_shape = isinstance(data, dict) and set(data.keys()) == {"route"}
        route = data.get("route") if isinstance(data, dict) else None

        if not is_valid_shape or route not in allowed_routes:
            logging.warning(
                f"[STEP1a] Router output không hợp lệ: data={data!r} — fallback out_of_domain"
            )
            route = "out_of_domain"
        response_style = "legal" if route == "use_tool" else "natural"

        logging.info(f"[STEP1a] route={route!r}, style={response_style!r}")
        return {
            "route": route,
            "response_style": response_style,
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
            # Reset các field rewrite để tránh sót state cũ
            "legal_query": "",
            "entities": {},
            "sub_queries": [],
            "complexity_level": 1,
        }
    except asyncio.TimeoutError:
        logging.warning(
            f"[STEP1a] Router timeout sau {_ROUTER_TIMEOUT}s — fallback use_tool"
        )
        return {
            "route": "use_tool",
            "response_style": "legal",
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
            "legal_query": "",
            "entities": {},
            "sub_queries": [],
            "complexity_level": 2,
        }
    except Exception as e:
        logging.error(f"[STEP1a] Lỗi: {e} — fallback use_tool")
        return {
            "route": "use_tool",
            "response_style": "legal",
            "standalone_question": True,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
            "legal_query": "",
            "entities": {},
            "sub_queries": [],
            "complexity_level": 2,
        }
