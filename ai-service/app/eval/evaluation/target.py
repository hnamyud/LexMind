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
_RE_CANONICAL_NODE_ID_TAG = re.compile(r"<canonical_node_id>([^<]+)</canonical_node_id>", re.IGNORECASE)
_RE_CANONICAL_NODE_IDS_TAG = re.compile(r"<canonical_node_ids>([^<]+)</canonical_node_ids>", re.IGNORECASE)
_RE_CANONICAL_NODE_ID_ATTR = re.compile(r'canonical_node_id="([^"]+)"', re.IGNORECASE)
_RE_CANONICAL_NODE_IDS_ATTR = re.compile(r'canonical_node_ids="([^"]+)"', re.IGNORECASE)
_RE_PATH_TEXT = re.compile(r"<path>([\s\S]*?)</path>", re.IGNORECASE)
_RE_REL_PATH_ATTR = re.compile(r'\spath="([^"]+)"', re.IGNORECASE)

# Whitelist node IDs được phép đưa vào prompt chấm.
# Hỗ trợ cả format cũ và mới (có tiền tố doc_ref):
# - dieu_7          / nd168_2024_dieu_7
# - d7_k7           / nd168_2024_d7_k7
# - d7_k7_c         / nd168_2024_d7_k7_c / l35_2024_d13_k1_a
_RE_ALLOWED_GRADING_NODE_ID = re.compile(
    r"^(?:[a-z]\w+_\d{4}_)?(?:dieu_\d+|d\d+(?:_k\d+(?:_[\wđ]+)?)?)$",
    re.IGNORECASE,
)

# Regex helpers để parse XML fields từ context block
_RE_CONTENT = re.compile(r"<content>([\s\S]*?)</content>", re.IGNORECASE)
_RE_PATH = re.compile(r"<path>([\s\S]*?)</path>", re.IGNORECASE)
_RE_SOURCE_TITLE = re.compile(r"<source_title>([\s\S]*?)</source_title>", re.IGNORECASE)
_RE_REL = re.compile(r'<rel[^>]*type="([^"]*)"[^>]*>([\s\S]*?)</rel>', re.IGNORECASE)


def _unescape_xml(text: str) -> str:
    """Unescape XML entities về ký tự gốc."""
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )


def _is_allowed_grading_node_id(node_id: str) -> bool:
    """Kiểm tra node_id có thuộc nhóm node được phép dùng khi evaluation hay không."""
    if not node_id:
        return False
    return _RE_ALLOWED_GRADING_NODE_ID.match(node_id.strip()) is not None


def _node_id_from_path(path: str) -> str | None:
    """Build legal node id từ path dạng 'Luật ... > Điều X > Khoản Y > Điểm Z'."""
    path = _unescape_xml(path or "").strip()
    if not path:
        return None

    low = path.lower()
    if "nghị định 168" in low or "nghi dinh 168" in low:
        doc_ref = "nd168_2024"
    elif "luật trật tự" in low or "luat trat tu" in low:
        doc_ref = "l36_2024"
    elif "luật đường bộ" in low or "luat duong bo" in low:
        doc_ref = "l35_2024"
    else:
        return None

    article_m = re.search(r"Điều\s*(\d+)", path, re.IGNORECASE)
    clause_m = re.search(r"Khoản\s*(\d+)", path, re.IGNORECASE)
    point_m = re.search(r"Điểm\s*([a-zđ])", path, re.IGNORECASE)
    if not article_m:
        return None

    node_id = f"{doc_ref}_d{article_m.group(1)}"
    if clause_m:
        node_id += f"_k{clause_m.group(1)}"
    if point_m:
        node_id += f"_{point_m.group(1).lower()}"
    return node_id


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


def _xml_block_to_readable(node_id: str, block: str) -> str:
    """
    Chuyển đổi một XML source block sang plain text dễ đọc cho LLM grader.

    Input (XML block):
        <source id="nd168_2024_d7_k7_c" score="0.031" ...>
          <doc_ref>nd168_2024</doc_ref>
          <source_title>Nghị định 168/2024/NĐ-CP</source_title>
          <path>Điều 7 > Khoản 7 > Điểm c</path>
          <content>Không chấp hành hiệu lệnh...</content>
          <relationships>
            <rel type="GAY_RA" id="csq_1">Phạt tiền từ 4.000.000...</rel>
            <rel type="AP_DUNG_CHO" id="subj_xe_may">Xe mô tô hai bánh...</rel>
          </relationships>
        </source>

    Output (plain text):
        [nd168_2024_d7_k7_c | Điều 7 > Khoản 7 > Điểm c | Nghị định 168/2024/NĐ-CP]
        Nội dung: Không chấp hành hiệu lệnh...
        → Hậu quả/Mức phạt: Phạt tiền từ 4.000.000...
        → Áp dụng cho: Xe mô tô hai bánh...
    """
    # Extract các field
    path_m = _RE_PATH.search(block)
    doc_title_m = _RE_SOURCE_TITLE.search(block)
    content_m = _RE_CONTENT.search(block)

    path = _unescape_xml(path_m.group(1).strip()) if path_m else ""
    doc_title = _unescape_xml(doc_title_m.group(1).strip()) if doc_title_m else ""
    content = _unescape_xml(content_m.group(1).strip()) if content_m else ""

    # Header line
    header_parts = [node_id]
    if path:
        header_parts.append(path)
    if doc_title:
        header_parts.append(doc_title)
    header = "[" + " | ".join(header_parts) + "]"

    lines = [header]
    if content:
        lines.append(f"Nội dung: {content}")

    # Extract relationships — phân loại theo type
    rel_type_labels = {
        "GAY_RA": "Hậu quả/Mức phạt",
        "HINH_PHAT_BO_SUNG": "Hình phạt bổ sung",
        "TRICH_DAN": "Trích dẫn",
        "AP_DUNG_CHO": "Áp dụng cho",
        "DIEU_KIEN": "Điều kiện",
        "LIEN_QUAN": "Liên quan",
    }
    for rel_m in _RE_REL.finditer(block):
        rel_type = rel_m.group(1).strip().upper()
        rel_text = _unescape_xml(rel_m.group(2).strip())
        if not rel_text:
            continue
        label = rel_type_labels.get(rel_type, rel_type)
        lines.append(f"→ {label}: {rel_text}")

    return "\n".join(lines)


def _build_groundedness_context(context: str) -> str:
    """
    Context cho groundedness: reformat XML sang plain text dễ đọc.
    Giữ toàn bộ thông tin (content + relationships) nhưng bỏ XML tags.
    """
    blocks = _iter_context_blocks(context)
    if not blocks:
        return context  # fallback raw context

    readable_blocks = [
        _xml_block_to_readable(node_id, block)
        for node_id, block in blocks
    ]
    readable_blocks = [b for b in readable_blocks if b]
    return "\n\n---\n\n".join(readable_blocks) if readable_blocks else context


def _extract_retrieved_nodes(context: str, legal_only: bool = False) -> list[str]:
    """
    Parse danh sách node IDs từ context text trả về bởi graph retriever.
    Trả về list unique, theo thứ tự xuất hiện.
    """
    if not context:
        return []
    seen: set[str] = set()
    nodes: list[str] = []

    def _add_node(node_id: str) -> None:
        if not node_id:
            return
        _id = node_id.strip()
        if not _id:
            return
        if legal_only and not _is_allowed_grading_node_id(_id):
            return
        if _id not in seen:
            seen.add(_id)
            nodes.append(_id)

    def _split_ids(value: str) -> list[str]:
        if not value:
            return []
        return [x.strip() for x in re.split(r"[|,]", value) if x and x.strip()]

    # Ưu tiên canonical IDs (tag + attr)
    for m in _RE_CANONICAL_NODE_ID_TAG.finditer(context):
        _add_node(_unescape_xml(m.group(1)))
    for m in _RE_CANONICAL_NODE_ID_ATTR.finditer(context):
        _add_node(_unescape_xml(m.group(1)))
    for m in _RE_CANONICAL_NODE_IDS_TAG.finditer(context):
        for cid in _split_ids(_unescape_xml(m.group(1))):
            _add_node(cid)
    for m in _RE_CANONICAL_NODE_IDS_ATTR.finditer(context):
        for cid in _split_ids(_unescape_xml(m.group(1))):
            _add_node(cid)

    # Fallback bổ sung: parse path thành legal node id.
    # Dùng cho case context có path/citation chuẩn nhưng thiếu canonical hoặc source id bị non-legal.
    for m in _RE_PATH_TEXT.finditer(context):
        _add_node(_node_id_from_path(m.group(1)))
    for m in _RE_REL_PATH_ATTR.finditer(context):
        _add_node(_node_id_from_path(m.group(1)))

    # Fallback về source.id nếu chưa có canonical
    if not nodes:
        for m in _RE_GRAPH_SOURCE.finditer(context):
            _add_node(m.group(1))

    return nodes


def _extract_retrieved_nodes_from_sources(
    sources: list[dict], legal_only: bool = False
) -> list[str]:
    """Extract graph node IDs directly from metadata sources list."""
    seen: set[str] = set()
    nodes: list[str] = []
    def _split_ids(value: object) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [x.strip() for x in re.split(r"[|,]", str(value)) if x and x.strip()]

    for src in sources or []:
        if not isinstance(src, dict):
            continue
        if src.get("type") != "knowledge_graph":
            continue

        candidate_ids: list[str] = []
        canonical_id = src.get("canonical_node_id")
        if canonical_id:
            candidate_ids.append(str(canonical_id).strip())
        candidate_ids.extend(_split_ids(src.get("canonical_node_ids")))
        if not candidate_ids:
            node_id = src.get("id")
            if node_id:
                candidate_ids.append(str(node_id).strip())

        for node_id in candidate_ids:
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

    Input  : question, expected_behavior
    Output (dùng bởi evaluators):
        answer               — câu trả lời AI (dùng bởi tất cả evaluators)
        groundedness_context — plain text context để check hallucination
        context              — raw XML context (fallback)
        retrieved_nodes      — node IDs pháp lý để so với reference_nodes
        verdict              — sufficient | needs_clarification | not_found
        cache_hit, node_timings

    NOTE: citation_accuracy đọc expected_citations từ dataset, KHÔNG cần context build riêng.
    """
    import asyncio
    import logging

    question = inputs["question"]
    sample_id = inputs.get("id") or uuid.uuid4().hex[:8]

    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 3  # seconds — exponential backoff: 3s, 6s

    answer = ""
    context = ""
    verdict = ""
    response_text = ""

    for attempt in range(MAX_RETRIES):
        # Dùng full UUID để đảm bảo thread_id hoàn toàn unique khi chạy multi-worker.
        eval_conversation_id = f"eval_{sample_id}_{uuid.uuid4().hex}"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
        except (httpx.ReadTimeout, httpx.HTTPStatusError) as exc:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logging.warning(
                    f"[Eval] {sample_id} attempt {attempt + 1} failed: {exc}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
                continue
            if isinstance(exc, httpx.HTTPStatusError):
                raise RuntimeError(
                    f"AI service returned HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            raise RuntimeError(
                f"AI service timeout after {MAX_RETRIES} attempts for {sample_id}"
            ) from exc

        response_text = response.text

        # Quick check: eval chỉ chấp nhận response có answer event.
        # Metadata-only response thường là pipeline rỗng/early-fail nhưng trước đây vẫn bị tính là hợp lệ.
        has_answer = '"type": "answer"' in response_text or '"type":"answer"' in response_text
        has_metadata = '"type": "metadata"' in response_text or '"type":"metadata"' in response_text

        if has_answer:
            break  # Response hợp lệ → thoát retry loop

        # Response rỗng hoặc thiếu content → retry
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_DELAY_BASE * (2 ** attempt)
            logging.warning(
                f"[Eval] {sample_id} attempt {attempt + 1}: empty response "
                f"(len={len(response_text)}, has_answer={has_answer}, has_metadata={has_metadata}). "
                f"Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)
        else:
            raise RuntimeError(
                f"[Eval] {sample_id}: empty response after {MAX_RETRIES} attempts. "
                f"has_answer={has_answer}, has_metadata={has_metadata}, "
                f"preview={response_text[:300]}"
            )

    # Parse NDJSON stream
    cache_hit = False
    node_timings = {}
    sources = []

    for line in response_text.strip().split("\n"):
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
                context     = payload.get("context", context)
                verdict     = payload.get("reflector_verdict", verdict)
                cache_hit   = payload.get("cacheHit", cache_hit)
                node_timings = payload.get("nodeTimings", node_timings)
                sources     = payload.get("sources", sources)
                # Backward-compat (flat metadata schema)
                context     = event.get("context", context)
                verdict     = event.get("reflector_verdict", verdict)
                cache_hit   = event.get("cacheHit", cache_hit)
                node_timings = event.get("nodeTimings", node_timings)
        except json.JSONDecodeError:
            continue

    # groundedness cần plain text — convert XML → readable
    groundedness_context = _build_groundedness_context(context)

    # Node IDs pháp lý để so sánh với reference_nodes trong dataset
    retrieved_nodes = _extract_retrieved_nodes(context, legal_only=True)
    if not retrieved_nodes:
        retrieved_nodes = _extract_retrieved_nodes_from_sources(sources, legal_only=True)

    expected_behavior = inputs.get("expected_behavior", "answer")
    if not answer.strip():
        raise RuntimeError(
            f"[Eval] {sample_id}: pipeline returned no answer text. "
            f"node_timings={node_timings}, response_preview={response_text[:300]}"
        )
    if expected_behavior == "answer" and not context and not retrieved_nodes:
        raise RuntimeError(
            f"[Eval] {sample_id}: answer question completed without retrieval context. "
            f"node_timings={node_timings}, answer_preview={answer[:200]}"
        )

    return {
        "answer": answer,
        "groundedness_context": groundedness_context,
        "context": context,
        "retrieved_nodes": retrieved_nodes,
        "verdict": verdict,
        "cache_hit": cache_hit,
        "node_timings": node_timings,
    }
