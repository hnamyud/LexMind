import os
import re
import httpx
import json
import uuid
from langsmith import traceable

AI_SERVICE_URL = os.getenv("LEXMIND_AI_SERVICE_URL", "http://localhost:8001").rstrip(
    "/"
)
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET")

# Regex parse node IDs từ context XML (format: <source id="nd168_2024_d7_k7_c" score="0.85" ...>)
_RE_GRAPH_SOURCE = re.compile(r'<source\s+id="([^"]+)"\s+score="([\d.]+)"')

# Whitelist node IDs được phép đưa vào prompt chấm.
# Hỗ trợ cả format cũ và mới (có tiền tố doc_ref):
# - dieu_7          / nd168_2024_dieu_7
# - d7_k7           / nd168_2024_d7_k7
# - d7_k7_c         / nd168_2024_d7_k7_c / l35_2024_d13_k1_a
_RE_ALLOWED_GRADING_NODE_ID = re.compile(
    r"^(?:[a-z]\w+_\d{4}_)?(?:dieu_\d+|d\d+(?:_k\d+(?:_[\wđ]+)?)?)$",
    re.IGNORECASE,
)


def _is_allowed_grading_node_id(node_id: str) -> bool:
    """Kiểm tra node_id có thuộc nhóm node được phép dùng khi evaluation hay không."""
    if not node_id:
        return False
    return _RE_ALLOWED_GRADING_NODE_ID.match(node_id.strip()) is not None


def _iter_context_blocks(context: str) -> list[tuple[str, str]]:
    """Tách context XML thành danh sách (node_id, block)."""
    if not context:
        return []

    matches = list(_RE_GRAPH_SOURCE.finditer(context))
    if not matches:
        return []

    blocks: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        node_id = match.group(1)
        # Block starts at <source tag, ends before next <source tag
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(context)
        block = context[start:end].strip()
        if block:
            blocks.append((node_id, block))
    return blocks


def _strip_graph_relationships(block: str) -> str:
    """Loại bỏ phần quan hệ đồ thị (<relationships> tag) để giảm nhiễu khi chấm LLM."""
    if not block:
        return ""

    # Strip XML relationships section
    import re as _re

    cleaned = _re.sub(r"\s*<relationships>[\s\S]*?</relationships>", "", block)
    cleaned = cleaned.strip()
    # Also remove the closing </source> tag for cleanliness
    cleaned = _re.sub(r"\s*</source>\s*$", "", cleaned).strip()
    return cleaned if cleaned else block


def _build_groundedness_context(context: str) -> str:
    """
    Context cho groundedness: giữ TOÀN BỘ block bao gồm cả quan hệ đồ thị.
    Grader cần thấy mức phạt từ node ⚖️ Hậu quả để verify hallucination.
    CHỈ cắt các node không phải nguồn gốc pháp lý (action_, hv_, cond_...).
    """
    blocks = _iter_context_blocks(context)
    if not blocks:
        return context  # fallback raw context

    # Giữ toàn bộ block — KHÔNG strip quan hệ đồ thị
    return "\n\n".join(block for _, block in blocks)


def _build_citation_context(context: str) -> str:
    """
    Context cho citation: chỉ giữ node điều/khoản/điểm và cắt phần quan hệ.

    Dùng để kiểm tra trích dẫn điều khoản, tránh nhiễu từ node hành vi/hậu quả.
    """
    blocks = _iter_context_blocks(context)
    if not blocks:
        return ""

    kept: list[str] = []
    for node_id, block in blocks:
        if not _RE_ALLOWED_GRADING_NODE_ID.match(node_id.strip()):
            continue
        cleaned = _strip_graph_relationships(block)
        if cleaned:
            kept.append(cleaned)

    return "\n\n".join(kept)


def _extract_retrieved_nodes(context: str, legal_only: bool = False) -> list[str]:
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
        if legal_only and not _is_allowed_grading_node_id(node_id):
            continue
        if node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
    return nodes


def _extract_retrieved_nodes_from_sources(
    sources: list[dict], legal_only: bool = False
) -> list[str]:
    """Extract graph node IDs directly from metadata sources list."""
    seen: set[str] = set()
    nodes: list[str] = []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        node_id = src.get("id") if src.get("type") == "knowledge_graph" else None
        if legal_only and not _is_allowed_grading_node_id(node_id):
            continue
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
        context         : str        — raw text context từ Neo4j
        groundedness_context : str   — context đã cắt quan hệ, giữ toàn bộ node nguồn
        citation_context: str        — context đã cắt quan hệ, chỉ giữ node điều/khoản/điểm
        retrieved_nodes_legal : list[str] — node pháp lý dùng cho retrieval_node_match
        retrieved_nodes_all   : list[str] — toàn bộ node retrieve để debug
        retrieved_nodes : list[str]  — alias backward-compatible của retrieved_nodes_legal
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
                headers["INTERNAL-SECRET"] = INTERNAL_SECRET

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
    grading_context = ""
    groundedness_context = ""
    citation_context = ""
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
                payload = (
                    event.get("content", {})
                    if isinstance(event.get("content"), dict)
                    else {}
                )

                # New schema (preferred): metadata.content.{...}
                context = payload.get("context", context)
                verdict = payload.get("reflector_verdict", verdict)
                cache_hit = payload.get("cacheHit", cache_hit)
                node_timings = payload.get("nodeTimings", node_timings)
                sources = payload.get("sources", sources)

                # Backward-compat schema: metadata.{...}
                context = event.get("context", context)
                verdict = event.get("reflector_verdict", verdict)
                cache_hit = event.get("cacheHit", cache_hit)
                node_timings = event.get("nodeTimings", node_timings)
        except json.JSONDecodeError:
            continue

    groundedness_context = _build_groundedness_context(context)
    citation_context = _build_citation_context(context)
    grading_context = citation_context

    # Parse node IDs từ context text để map với reference_nodes trong dataset
    retrieved_nodes_all = _extract_retrieved_nodes(context, legal_only=False)
    retrieved_nodes_legal = _extract_retrieved_nodes(context, legal_only=True)
    if not retrieved_nodes_all:
        retrieved_nodes_all = _extract_retrieved_nodes_from_sources(
            sources, legal_only=False
        )
    if not retrieved_nodes_legal:
        retrieved_nodes_legal = _extract_retrieved_nodes_from_sources(
            sources, legal_only=True
        )

    return {
        "answer": answer,
        "context": context,  # Raw text — dùng cho groundedness + citation
        "groundedness_context": groundedness_context,  # Full nguồn (đã bỏ quan hệ) cho groundedness
        "citation_context": citation_context,  # Chỉ điều/khoản/điểm cho citation
        "grading_context": grading_context,  # Backward-compatible alias của citation_context
        "retrieved_nodes_all": retrieved_nodes_all,  # Toàn bộ node đã retrieve (debug)
        "retrieved_nodes_legal": retrieved_nodes_legal,  # Node pháp lý để chấm retrieval
        "retrieved_nodes": retrieved_nodes_legal,  # Backward-compatible field
        "verdict": verdict,  # sufficient / needs_clarification / not_found
        "cache_hit": cache_hit,
        "node_timings": node_timings,
    }
