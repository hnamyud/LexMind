"""
nodes/web_search.py
───────────────────
Step 3c — Web Search Fallback: tìm kiếm web khi Neo4j không có dữ liệu.

Option B: hàm nhận `self` (RAGService instance) làm tham số đầu tiên.
"""

import logging

from langchain_core.messages import HumanMessage


async def _node_web_search_fallback(self, state: dict) -> dict:
    """Step 3c: Tìm kiếm web khi Neo4j không có dữ liệu về hành vi."""
    messages = state.get("messages", [])
    question = ""
    for msg in messages:
        if isinstance(msg, HumanMessage):
            question = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not question:
        return {"context": "(Không xác định được câu hỏi để tìm kiếm web.)", "web_sources": []}

    web_tool = next((t for t in self._tools if t.name == "web_search"), None)
    if not web_tool:
        logging.warning("[STEP3c] web_search không khả dụng — thiếu SERPER_API_KEY.")
        return {"context": "(Web search không khả dụng.)", "web_sources": []}

    logging.info(f"[STEP3c] Tìm web cho: {question[:80]}")
    try:
        result, web_sources = await web_tool._execute_with_sources(query=question, num=5)
        logging.info(f"[STEP3c] Tìm được {len(web_sources)} nguồn web.")
        return {
            "context": (
                "⚠️ Thông tin KHÔNG có trong Nghị định 168/2024/NĐ-CP. "
                "Kết quả bổ sung từ tìm kiếm web:\n\n" + result
            ),
            "web_sources": web_sources,
        }
    except Exception as e:
        logging.error(f"[STEP3c] Lỗi web search: {e}")
        return {"context": f"Lỗi khi tìm kiếm web: {e}", "web_sources": []}
