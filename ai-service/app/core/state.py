from typing import TypedDict, List, Any, Annotated
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    # ── Conversation memory (dùng với LangGraph checkpointer) ────────────────
    # `add_messages` là reducer mặc định của LangGraph:
    # thay vì ghi đè toàn bộ list, nó *append* message mới vào cuối.
    # Nhờ đó lịch sử hội thoại được tích lũy qua các lần invoke.
    messages: Annotated[List[Any], add_messages]

    # ── Step 1: Router + Extractor output ────────────────────────────────────
    route: str         # "use_tool" | "direct_answer"
    legal_query: str   # thuật ngữ pháp lý đã chuẩn hóa
    entities: dict     # {violation, vehicle_type, subject, conditions[]}

    # ── Step 2: Retriever output ──────────────────────────────────────────────
    context: str       # raw context text từ Neo4j (hoặc web)

    # ── Step 3: Reflector output ──────────────────────────────────────────────
    reflection: str              # "sufficient" | "needs_clarification" | "not_found"
    clarification_question: str  # câu hỏi ngược lại cho user (nếu needs_clarification)

    # ── Web sources (khi dùng web search fallback) ────────────────────────────
    web_sources: List[dict]      # [{url, title}, ...] — nguồn web đã tham khảo
