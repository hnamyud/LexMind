"""
nodes/safety.py
────────────────
Shared safety helpers for prompt-injection/meta-probing detection.
"""

import re


META_OR_INJECTION_PATTERNS: tuple[str, ...] = (
    r"\b(prompt|system prompt|developer prompt|hidden prompt)\b",
    r"\b(chain[ -]?of[ -]?thought|cot|reasoning)\b",
    r"\b(quy tắc bắt buộc|nguyên tắc nội bộ|cơ chế nội bộ|luật nội bộ)\b",
    r"\b(audit nội bộ|kiểm thử bảo mật|security audit|pentest)\b",
    r"\b(nguyên tắc bạn tuân theo|quy tắc của bạn|chính sách nội bộ)\b",
    r"\b(bạn bị cấm làm gì|nguyên tắc ẩn|hướng dẫn nội bộ)\b",
    r"\b(in ra|show|dump|xuất ra).*(prompt|rule|quy tắc|hướng dẫn)\b",
    r"\b(liệt kê|mô tả|cho biết).*(quy tắc|nguyên tắc|cơ chế|policy)\b",
    r"\b(bỏ qua|ignore).*(hướng dẫn|instructions|system)\b",
    r"\bignore\s+previous\s+instructions\b",
    r"\bsystem\s*:\b",
    r"\bdeveloper\s*:\b",
    r"\bact\s+as\b",
    r"\breveal\s+(?:hidden\s+)?prompt\b",
    r"<\s*system[-_ ]?reminder\s*>",
    r"<\s*/\s*system[-_ ]?reminder\s*>",
    r"\boperational mode has changed\b",
    r"\bread-only mode\b",
    r"\bstrictly forbidden\b",
    r"\binform the user\b",
    r"\berror\s*:\s*cannot read\b",
)


def is_meta_or_injection_query(text: str) -> bool:
    q = (text or "").lower()
    if not q:
        return False
    return any(re.search(p, q, re.IGNORECASE) for p in META_OR_INJECTION_PATTERNS)


def generic_refusal_message() -> str:
    """Fail-closed generic response, không tiết lộ lý do block."""
    return (
        "Mình không thể hỗ trợ nội dung này. "
        "Nếu bạn muốn, mình có thể hỗ trợ một câu hỏi pháp lý giao thông cụ thể."
    )
