import os
import re
import httpx
import json
import uuid
from langsmith import traceable

AI_SERVICE_URL = os.getenv("LEXMIND_AI_SERVICE_URL", "http://localhost:8001").rstrip("/")
INTERNAL_SECRET = os.getenv("X-Internal-Secret") or os.getenv("INTERNAL_SECRET")

# Regex parse node IDs từ context text (tái sử dụng pattern của RAGService)
# Header format: "--- Nguồn d7_k7_c (score: 0.85 | hop: 0 | ...) ---"
_RE_GRAPH_SOURCE = re.compile(
    r"---\s*Nguồn\s+(\S+)\s*\(score:\s*[\d.]+\s*\|[^)]*\)\s*---"
)


def _extract_retrieved_nodes(context: str) -> list[str]:
    """
    Parse danh sách node IDs từ context text trả về bởi graph retriever.
    Trả về list unique, theo thứ tự xuất hiện.
    """
    if not context:
        return []
    seen: set[str] = set()
    nodes: list[str] = []
    for m in _RE_GRAPH_SOURCE.finditer(context):
        node_id = m.group(1)
        if node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
    return nodes


def _extract_retrieved_nodes_from_sources(sources: list[dict]) -> list[str]:
    """Extract graph node IDs directly from metadata sources list."""
    seen: set[str] = set()
    nodes: list[str] = []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        node_id = src.get("id") if src.get("type") == "knowledge_graph" else None
        if node_id and node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
    return nodes


@traceable()
async def lexmind_target(inputs: dict) -> dict:
    """
    Wrap LexMind FastAPI pipeline để LangSmith evaluate.

    Input (từ LangSmith dataset):
        question        : str  — câu hỏi
        question_type   : str  — factual | multi_hop | comparison | adversarial | oos
        expected_behavior: str — answer | refuse | clarify

    Output (được dùng bởi 5 evaluators):
        answer          : str        — câu trả lời của AI
        context         : str        — raw text context từ Neo4j (dùng cho groundedness + citation)
        retrieved_nodes : list[str]  — node IDs đã retrieve (dùng cho retrieval_node_match)
        verdict         : str        — sufficient | needs_clarification | not_found
        cache_hit       : bool
        node_timings    : dict
    """
    question = inputs["question"]
    sample_id = inputs.get("id") or uuid.uuid4().hex[:8]
    # Dùng full UUID để đảm bảo thread_id hoàn toàn unique khi chạy multi-worker.
    # hex[:6] chỉ có ~16M khả năng → dễ collision khi nhiều câu cùng sample_id chạy song song.
    eval_conversation_id = f"eval_{sample_id}_{uuid.uuid4().hex}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {}
            if INTERNAL_SECRET:
                headers["X-Internal-Secret"] = INTERNAL_SECRET

            response = await client.post(
                f"{AI_SERVICE_URL}/ask/stream",
                json={
                    "question": question,
                    "conversation_id": eval_conversation_id,
                    "enable_web_search": False,
                    "enable_cache": False,
                },
                headers=headers,
            )
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot connect to AI service at {AI_SERVICE_URL}. "
            "Ensure the service is running and reachable."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"AI service returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc

    # Parse NDJSON stream — gom lại toàn bộ events
    answer = ""
    context = ""
    verdict = ""
    cache_hit = False
    node_timings = {}
    sources = []

    for line in response.text.strip().split("\n"):
        if not line:
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "answer":
                answer += event.get("content", "")
            elif event.get("type") == "metadata":
                payload = event.get("content", {}) if isinstance(event.get("content"), dict) else {}

                # New schema (preferred): metadata.content.{...}
                context      = payload.get("context", context)
                verdict      = payload.get("reflector_verdict", verdict)
                cache_hit    = payload.get("cacheHit", cache_hit)
                node_timings = payload.get("nodeTimings", node_timings)
                sources      = payload.get("sources", sources)

                # Backward-compat schema: metadata.{...}
                context      = event.get("context", context)
                verdict      = event.get("reflector_verdict", verdict)
                cache_hit    = event.get("cacheHit", cache_hit)
                node_timings = event.get("nodeTimings", node_timings)
        except json.JSONDecodeError:
            continue

    # Parse node IDs từ context text để map với reference_nodes trong dataset
    retrieved_nodes = _extract_retrieved_nodes(context)
    if not retrieved_nodes:
        retrieved_nodes = _extract_retrieved_nodes_from_sources(sources)

    return {
        "answer":          answer,
        "context":         context,          # Raw text — dùng cho groundedness + citation
        "retrieved_nodes": retrieved_nodes,  # List node IDs — dùng cho retrieval_node_match
        "verdict":         verdict,          # sufficient / needs_clarification / not_found
        "cache_hit":       cache_hit,
        "node_timings":    node_timings,
    }