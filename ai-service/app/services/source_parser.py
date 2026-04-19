"""
services/source_parser.py
─────────────────────────
Parse và trích xuất nguồn tham chiếu pháp lý từ context string.

Hàm public:
  parse_legal_anchors(context)   → list[str]  - Điều/Khoản/Điểm anchors
  extract_graph_sources(context) → list[dict] - Neo4j graph sources với score
  extract_web_sources(context)   → list[dict] - Web URL sources
"""

import re


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_GRAPH_SOURCE = re.compile(r'<source\s+id="([^"]+)"\s+score="([\d.]+)"')
_RE_WEB_URL = re.compile(r"^URL\s*:\s*(https?://\S+)", re.MULTILINE)

# Nhận diện các chuỗi chứa "Điều", "Khoản", "Điểm" (có thể độc lập hoặc kết hợp)
# Bắt được: "Điều 18", "Khoản 8", "Điểm a", "Điểm a Khoản 8 Điều 18", v.v.
_RE_DIEU_KHOAN = re.compile(
    r"(?:Điểm\s+[a-zđ0-9]+\s+)?(?:Khoản\s+\d+\s+)?(?:Điều\s+\d+)|(?:Khoản\s+\d+)|(?:Điểm\s+[a-zđ0-9]+(?:\s+Khoản\s+\d+)?)",
    re.IGNORECASE,
)

# Parse entity IDs — hỗ trợ cả format cũ và mới có prefix doc_ref:
#   Cũ: d18_k8_a             → "Điều 18 Khoản 8 Điểm a"
#   Mới: nd168_2024_d7_k7_c  → "Điều 7 Khoản 7 Điểm c"
#        l35_2024_dieu_13     → "Điều 13"
_RE_ENTITY_ID = re.compile(
    r"\b(?:[a-z]\w+_\d{4}_)?" r"(?:dieu_(\d+)|d(\d+)(?:_k(\d+)(?:_([a-zđ]+))?)?)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Source parsers
# ---------------------------------------------------------------------------


def parse_legal_anchors(context: str) -> list[str]:
    """
    Parse nhanh các anchor pháp lý (Điều/Khoản/Điểm) từ context trả về bởi retriever.
    Lọc bỏ các block có score thấp so với top score để tránh nhiễu.
    Dedup + giữ thứ tự xuất hiện, tối đa 8 anchors để tránh quá dài.

    Parse từ 2 nguồn:
    1. Entity IDs dạng: d18_k8_a → "Điều 18 Khoản 8 Điểm a"
    2. Text anchors dạng: "Điều 18", "Khoản 8", "Điểm a Khoản 8", v.v.
    """
    if not context or "Không tìm thấy" in context:
        return []

    # Tách context thành các block theo thẻ <source>
    headers = list(_RE_GRAPH_SOURCE.finditer(context))
    valid_context_text = context

    if headers:
        try:
            max_score = float(headers[0].group(2))
        except ValueError:
            max_score = 0.0

        threshold = max_score * 0.5
        kept_blocks = []

        for i, match in enumerate(headers):
            try:
                score = float(match.group(2))
            except ValueError:
                score = 0.0

            if score >= threshold:
                # block starts at the <source tag, ends before next <source tag
                start_idx = match.start()
                end_idx = (
                    headers[i + 1].start() if i + 1 < len(headers) else len(context)
                )
                kept_blocks.append(context[start_idx:end_idx])

        if kept_blocks:
            valid_context_text = "\n".join(kept_blocks)

    seen: set[str] = set()
    anchors: list[str] = []

    def capitalize_kw(match_obj):
        return match_obj.group(0).capitalize()

    # 1. Parse entity IDs
    # Groups: (dieu_N_only, dN_num, kN_num, letter)
    for m in _RE_ENTITY_ID.finditer(valid_context_text):
        dieu_only, d_num, k_num, diem_letter = m.groups()
        dieu_num = dieu_only or d_num  # dieu_13 hoặc d13
        parts = []
        if dieu_num:
            parts.append(f"Điều {dieu_num}")
        if k_num:
            parts.append(f"Khoản {k_num}")
        if diem_letter:
            parts.append(f"Điểm {diem_letter}")

        if parts:
            anchor = " ".join(parts)
            key = anchor.lower()
            if key not in seen:
                seen.add(key)
                anchors.append(anchor)

    # 2. Parse text anchors (Điều X, Khoản Y, Điểm Z, v.v.)
    for m in _RE_DIEU_KHOAN.finditer(valid_context_text):
        token = m.group(0).strip()
        token_clean = re.sub(
            r"(điểm|khoản|điều|mục)", capitalize_kw, token, flags=re.IGNORECASE
        )

        key = token_clean.lower()
        if key not in seen and "Điều này" not in token_clean:
            seen.add(key)
            anchors.append(token_clean)

    return anchors[:8]  # giới hạn 8 anchors


def extract_graph_sources(context: str) -> list[dict]:
    """Trích xuất nguồn từ Neo4j graph retrieval results (XML format)."""
    return [
        {"type": "knowledge_graph", "id": m.group(1), "score": float(m.group(2))}
        for m in _RE_GRAPH_SOURCE.finditer(context)
    ]


def extract_web_sources(context: str) -> list[dict]:
    """Trích xuất URL nguồn từ web search results."""
    return [{"type": "web", "url": m.group(1)} for m in _RE_WEB_URL.finditer(context)]
