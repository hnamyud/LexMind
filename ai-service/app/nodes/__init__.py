# nodes/__init__.py
# Re-export tất cả node implementations để graph/builder.py import gọn.
# Tất cả node functions đều theo Option B: nhận (self, state, ...) — bound methods.

from .base import _extract_ai_text, _load_prompt, _load_skill
from .router import _node_router
from .rewrite import _node_rewrite
from .retriever import (
    _node_retriever,
    _filter_context_for_reflector,
    _format_multi_violation_context,
)
from .reflector import (
    _node_reflector,
    _is_high_confidence_penalty_context,
    _is_high_confidence_provision_context,
)
from .generator import _node_generator
from .cache import _node_cache_check, _node_generator_cached
from .agent import _node_agent_direct, _node_agent_reject, _node_clarifier
from .web_search import _node_web_search_fallback

__all__ = [
    "_extract_ai_text",
    "_load_prompt",
    "_load_skill",
    "_node_router",
    "_node_rewrite",
    "_node_retriever",
    "_filter_context_for_reflector",
    "_format_multi_violation_context",
    "_node_reflector",
    "_is_high_confidence_penalty_context",
    "_is_high_confidence_provision_context",
    "_node_generator",
    "_node_cache_check",
    "_node_generator_cached",
    "_node_agent_direct",
    "_node_agent_reject",
    "_node_clarifier",
    "_node_web_search_fallback",
]
