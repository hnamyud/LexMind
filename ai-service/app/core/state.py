from typing import TypedDict, List, Any


class RAGState(TypedDict):
    question: str
    legal_query: str
    records: List[dict]
    context: str
    queue: Any  # asyncio.Queue dùng để stream labeled chunks ra ngoài
