"""
nodes/retriever.py
──────────────────
Step 2 — Retriever: tra cứu đồ thị tri thức (Neo4j) song song cho đa vi phạm.

Bao gồm:
  - _filter_context_for_reflector : lọc block context theo score threshold
  - _format_multi_violation_context: gộp N sub-contexts thành 1 string có cấu trúc
  - _node_retriever                : logic retrieval chính (single + multi-violation)

Option B: _node_retriever nhận `self` (RAGService) làm tham số đầu tiên.
_filter_context_for_reflector và _format_multi_violation_context là pure functions
(không cần self), nhưng cần biết _REFLECTOR_SCORE_THRESHOLD từ RAGService.
"""

import asyncio
import logging
import re


# ---------------------------------------------------------------------------
# Score threshold (mirror của RAGService._REFLECTOR_SCORE_THRESHOLD)
# Được override bởi RAGService nếu cần.
# ---------------------------------------------------------------------------
_REFLECTOR_SCORE_THRESHOLD: float = 0.012

_RE_CONTEXT_SOURCE_HEADER = re.compile(
    r"^---\s*Nguồn\s+\S+\s*\(score:\s*([\d.]+)\s*\|[^)]*\)\s*---\s*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Pre-reflector filter
# ---------------------------------------------------------------------------

def _filter_context_for_reflector(context: str, threshold: float = _REFLECTOR_SCORE_THRESHOLD) -> str:
    """
    Lọc block context trước khi chuyển sang reflector:
    - Chỉ giữ các block có score >= threshold
    - Nếu tất cả block bị loại → trả marker LOW_CONFIDENCE để trigger web search.
    """
    if not context:
        return context

    # Tôn trọng kết quả đã được graph tool đánh dấu low-confidence trước đó.
    if "[LOW_CONFIDENCE_THRESHOLD]" in context:
        return context

    headers = list(_RE_CONTEXT_SOURCE_HEADER.finditer(context))
    if not headers:
        return context

    kept_blocks: list[str] = []
    total_blocks = len(headers)

    for i, header in enumerate(headers):
        start = header.start()
        end = headers[i + 1].start() if i + 1 < total_blocks else len(context)
        block = context[start:end].strip()
        try:
            score = float(header.group(1))
        except Exception:
            score = 0.0

        if score >= threshold:
            kept_blocks.append(block)

    if not kept_blocks:
        low_confidence_msg = (
            "⚠️ [LOW_CONFIDENCE_THRESHOLD] "
            f"Tất cả kết quả retrieval đều dưới ngưỡng {threshold:.1f}. "
            "Nên chuyển sang tìm kiếm web để bổ sung."
        )
        logging.warning(
            f"[STEP2] Pre-reflector threshold filter removed all blocks: "
            f"kept=0/{total_blocks}, threshold={threshold:.1f}"
        )
        return low_confidence_msg

    filtered_context = "\n\n".join(kept_blocks)
    if len(kept_blocks) < total_blocks:
        logging.info(
            f"[STEP2] Pre-reflector threshold filter: kept={len(kept_blocks)}/{total_blocks}, "
            f"threshold={threshold:.1f}"
        )

    return filtered_context


# ---------------------------------------------------------------------------
# Multi-violation context formatter
# ---------------------------------------------------------------------------

def _format_multi_violation_context(sub_contexts: list[dict]) -> str:
    """
    Gộp N sub-contexts thành 1 context string có delimiter rõ ràng
    để Generator phân biệt dữ liệu từng vi phạm.
    """
    if not sub_contexts:
        return ""

    total = len(sub_contexts)
    SEP = "═" * 60

    parts = []
    for i, sc in enumerate(sub_contexts, 1):
        label = sc.get("label", f"Vi phạm {i}")
        ctx = sc.get("context", "")

        header = (
            f"\n{SEP}\n"
            f"  VI PHẠM {i}/{total}: {label}\n"
            f"{SEP}"
        )

        if ctx and "Không tìm thấy" not in ctx:
            parts.append(f"{header}\n{ctx}")
        else:
            parts.append(
                f"{header}\n"
                f"(Không tìm thấy thông tin cho vi phạm này trong đồ thị tri thức.)"
            )

    summary = (
        f"[MULTI-VIOLATION CONTEXT: {total} vi phạm riêng biệt]\n"
        f"Mỗi phần 'VI PHẠM X' chứa dữ liệu độc lập — "
        f"KHÔNG được ghép mức phạt từ vi phạm này sang vi phạm khác.\n"
    )

    return summary + "\n".join(parts)


# ---------------------------------------------------------------------------
# Retriever node (Option B — nhận self)
# ---------------------------------------------------------------------------

async def _node_retriever(self, state: dict) -> dict:
    """
    Step 2: Retrieval — xử lý cả single-violation và multi-violation.

    - Single violation (sub_queries rỗng): chạy 1 lần _arun() như cũ
    - Multi-violation (sub_queries không rỗng): chạy song song N lần
      _arun() qua asyncio.gather, rồi gộp kết quả có cấu trúc
    """
    sub_queries = state.get("sub_queries", [])
    legal_query = state.get("legal_query", "")
    entities = state.get("entities", {})

    graph_tool = next((t for t in self._tools if t.name == "search_legal_graph"), None)
    if not graph_tool:
        logging.error("[STEP2] GraphRetrievalTool không khả dụng.")
        return {"context": "", "sub_contexts": []}

    # Lấy threshold từ service instance (nếu override)
    threshold = getattr(self, "_REFLECTOR_SCORE_THRESHOLD", _REFLECTOR_SCORE_THRESHOLD)

    # ── Single-violation path (backward compatible) ───────────────
    if not sub_queries:
        if not legal_query:
            return {"context": "", "sub_contexts": []}

        logging.info(
            f"[STEP2] Single-query retrieval: query='{legal_query[:80]}' | "
            f"entities={entities}"
        )
        try:
            context = await graph_tool._arun(query=legal_query, entities=entities)
            context = _filter_context_for_reflector(context, threshold)
            return {"context": context, "sub_contexts": []}
        except Exception as e:
            logging.error(f"[STEP2] Lỗi: {e}")
            return {"context": "", "sub_contexts": []}

    # ── Multi-violation path (parallel retrieval) ─────────────────
    logging.info(
        f"[STEP2] Multi-query parallel retrieval: "
        f"{len(sub_queries)} sub-queries"
    )

    async def _retrieve_one(sq: dict) -> dict:
        q = sq.get("legal_query", "")
        e = sq.get("entities", {})
        label = sq.get("label", q[:30])
        if not q:
            return {"legal_query": q, "context": "", "label": label}
        try:
            ctx = await graph_tool._arun(query=q, entities=e)
            ctx = _filter_context_for_reflector(ctx, threshold)
            return {"legal_query": q, "context": ctx, "label": label}
        except Exception as ex:
            logging.error(f"[STEP2] Sub-query '{label}' error: {ex}")
            return {"legal_query": q, "context": "", "label": label}

    tasks = [_retrieve_one(sq) for sq in sub_queries]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    sub_contexts = [r for r in results if isinstance(r, dict)]

    # Build merged context with per-violation separation
    merged_context = _format_multi_violation_context(sub_contexts)

    logging.info(
        f"[STEP2] Parallel retrieval complete: "
        f"{len(sub_contexts)} sub-contexts, "
        f"merged context length={len(merged_context)}"
    )

    return {"context": merged_context, "sub_contexts": sub_contexts}
