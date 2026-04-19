"""
nodes/base.py
─────────────
Các helper dùng chung toàn bộ node pipeline:
  - _extract_ai_text : trích text thuần từ AIMessage
  - _load_prompt     : load YAML prompt template từ /prompts/
  - _load_skill      : load .md skill file từ /agent-skills/
"""

import logging
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SKILLS_DIR = Path(__file__).parent.parent / "agent-skills"


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_ai_text(msg: AIMessage) -> str:
    """Trích text thuần từ AIMessage (xử lý cả str lẫn list thinking chunks)."""
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# Prompt / Skill loaders
# ---------------------------------------------------------------------------

def _load_prompt(filename: str) -> str:
    """Load YAML prompt file, trả về string template."""
    path = _PROMPTS_DIR / filename
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Legacy schema: {template: "..."}
    if isinstance(data, dict) and isinstance(data.get("template"), str):
        return data["template"]

    # Router schema (new): {router_config: {prompt_template: "..."}}
    router_cfg = data.get("router_config") if isinstance(data, dict) else None
    if isinstance(router_cfg, dict) and isinstance(router_cfg.get("prompt_template"), str):
        return router_cfg["prompt_template"]

    raise KeyError(f"Prompt file '{filename}' thiếu key 'template' hoặc 'router_config.prompt_template'.")


def _load_skill(filename: str) -> str:
    """Load một agent-skill .md file, trả về nội dung text thuần."""
    path = _SKILLS_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logging.warning(f"[SKILL] Không tìm thấy skill file: {filename}")
        return ""
