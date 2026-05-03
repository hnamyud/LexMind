"""
nodes/followup.py
────────────────
Helpers cho nhận diện phản hồi xác nhận ngắn sau clarifier.
"""

import re


_CONFIRM_PREFIX = re.compile(
    r"^\s*(đúng vậy|đúng rồi|đúng|vâng|dạ đúng|dạ|ừ đúng|ừ|chính xác)\b[\s,.:;!?-]*",
    re.IGNORECASE,
)
_DENY_PREFIX = re.compile(
    r"^\s*(không phải|không đúng|không)\b[\s,.:;!?-]*",
    re.IGNORECASE,
)


def normalize_clarification_reply(text: str) -> dict:
    """
    Phân loại nhanh phản hồi user sau clarifier.
    Trả về:
      - reply_type: confirm_only | confirm_with_content | deny_only | deny_with_content | normal
      - remaining_text: phần còn lại sau khi bỏ filler/prefix
    """
    raw = (text or "").strip()
    if not raw:
        return {"reply_type": "normal", "remaining_text": ""}

    m_confirm = _CONFIRM_PREFIX.match(raw)
    if m_confirm:
        remaining = raw[m_confirm.end():].strip()
        return {
            "reply_type": "confirm_only" if not remaining else "confirm_with_content",
            "remaining_text": remaining,
        }

    m_deny = _DENY_PREFIX.match(raw)
    if m_deny:
        remaining = raw[m_deny.end():].strip()
        return {
            "reply_type": "deny_only" if not remaining else "deny_with_content",
            "remaining_text": remaining,
        }

    return {"reply_type": "normal", "remaining_text": raw}
