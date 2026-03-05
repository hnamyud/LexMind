from typing import TypedDict, List, Any
from langgraph.graph.message import add_messages
from typing import Annotated


class RAGState(TypedDict):
    # ── Core RAG fields ─────────────────────────────────────────────────────
    question: str
    legal_query: str
    records: List[dict]
    context: str
    queue: Any  # asyncio.Queue dùng để stream labeled chunks ra ngoài

    # ── Conversation memory (dùng với LangGraph checkpointer) ────────────────
    # `add_messages` là reducer mặc định của LangGraph:
    # thay vì ghi đè toàn bộ list, nó *append* message mới vào cuối.
    # Nhờ đó lịch sử hội thoại được tích lũy qua các lần invoke.
    messages: Annotated[List[Any], add_messages]
