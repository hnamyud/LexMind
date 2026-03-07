from typing import TypedDict, List, Any, Annotated
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    # ── Conversation memory (dùng với LangGraph checkpointer) ────────────────
    # `add_messages` là reducer mặc định của LangGraph:
    # thay vì ghi đè toàn bộ list, nó *append* message mới vào cuối.
    # Nhờ đó lịch sử hội thoại được tích lũy qua các lần invoke.
    messages: Annotated[List[Any], add_messages]
