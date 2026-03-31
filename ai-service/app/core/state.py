from typing import TypedDict, List, Any, Annotated
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    # ── Conversation memory (dùng với LangGraph checkpointer) ────────────────
    # `add_messages` là reducer mặc định của LangGraph:
    # thay vì ghi đè toàn bộ list, nó *append* message mới vào cuối.
    # Nhờ đó lịch sử hội thoại được tích lũy qua các lần invoke.
    messages: Annotated[List[Any], add_messages]

    # ── Step 1: Router + Extractor output ────────────────────────────────────
    route: str             # "use_tool" | "direct_answer" | "out_of_domain"
    legal_query: str       # thuật ngữ pháp lý đã chuẩn hóa
    entities: dict         # {violation, vehicle_type, subject, conditions[]}
    response_style: str    # "legal" (format cứng, trích dẫn luật) | "natural" (thân thiện)
    complexity_level: int  # 1=Simple | 2=Medium | 3=Complex — điều chỉnh thinking budget
    enable_web_search: bool  # False khi chạy RAGAS experiment — đọc từ config trong router node

    # ── Step 1b: Sub-query decomposition (multi-violation) ───────────────────
    sub_queries: List[dict]    # [{"legal_query": "...", "entities": {...}, "label": "..."}, ...]
                               # Rỗng [] nếu chỉ có 1 vi phạm

    # ── Step 2: Retriever output ─────────────────────────────────────────────
    context: str               # context text tổng hợp từ Neo4j (hoặc web)
    sub_contexts: List[dict]   # [{"legal_query": "...", "context": "...", "label": "..."}, ...]
                               # Rỗng [] nếu single-violation

    # ── Step 3: Reflector output ──────────────────────────────────────────────
    reflection: str              # "sufficient" | "needs_clarification" | "not_found"
    clarification_question: str  # câu hỏi ngược lại cho user (nếu needs_clarification)
    trigger_search: bool         # True nếu Graph data không khớp → force web search

    # ── Web sources (khi dùng web search fallback) ────────────────────────────
    web_sources: List[dict]      # [{url, title}, ...] — nguồn web đã tham khảo

    # ── Semantic Cache ─────────────────────────────────────────────────────────
    cache_hit: bool              # True nếu câu trả lời lấy từ semantic cache
    cached_response: str         # Nội dung response từ cache (nếu cache_hit=True)


