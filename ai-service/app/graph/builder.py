"""
graph/builder.py
────────────────
Xây dựng LangGraph StateGraph và định nghĩa routing functions.

Hàm public:
  build_graph(service) → compiled graph

Routing functions (pure — không cần self, đọc từ state):
  _route_after_router   : router → rewrite | agent_direct | agent_reject
  _route_after_cache    : cache_check → generator_cached | retriever
  _route_after_reflector: reflector → generator | clarifier | web_search_fallback
"""

import logging

from langgraph.graph import StateGraph, END

from app.core.state import RAGState


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route_after_router(state: RAGState) -> str:
    """Step 1a → rewrite (legal), direct_answer, hoặc reject."""
    route = state.get("route")
    if route == "direct_answer":
        return "agent_direct"
    if route == "out_of_domain":
        return "agent_reject"
    return "rewrite"  # use_tool → bước rewrite


def _route_after_cache(state: RAGState) -> str:
    """Cache check → generator_cached (nếu HIT) hoặc retriever (nếu MISS)."""
    if state.get("cache_hit", False):
        logging.info("[ROUTING] cache_hit=True → generator_cached (skip retriever/reflector)")
        return "generator_cached"
    return "retriever"


def _route_after_rewrite(state: RAGState) -> str:
    """Rewrite → cache_check (nếu bật cache) hoặc retriever (nếu tắt cache)."""
    if state.get("enable_cache", True):
        return "cache_check"

    logging.info("[ROUTING] enable_cache=False → Bỏ qua cache_check, đi thẳng retriever")
    return "retriever"


def _route_after_reflector(state: RAGState) -> str:
    """
    Step 3 → routing:
      trigger_search = true   → web_search_fallback (ưu tiên cao nhất — force search)
      sufficient              → generator (Step 4)
      needs_clarification     → clarifier (hỏi ngược user, rồi END)
      not_found               → web_search_fallback → generator

    NOTE: LangGraph KHÔNG truyền `config` vào routing function của add_conditional_edges.
    enable_web_search được lưu vào state bởi _node_router rồi đọc tại đây.
    """
    enable_web_search = state.get("enable_web_search", True)
    verdict = state.get("reflection", "sufficient")
    trigger_search = state.get("trigger_search", False)

    # ── Ưu tiên 0: Tắt thủ công qua Config (cho Testing RAGAS) ───────────
    if not enable_web_search:
        if trigger_search or verdict == "not_found":
            logging.info("[ROUTING] enable_web_search=False → Bỏ qua web_search_fallback, tiếp tục tới generator")
            return "generator"
        if verdict == "needs_clarification":
            return "clarifier"
        return "generator"

    # ── Ưu tiên 1: Force search ──────────────────────────────────────────
    if trigger_search:
        logging.info("[ROUTING] trigger_search=True → web_search_fallback")
        return "web_search_fallback"

    # ── Ưu tiên 2: Verdict routing ──────────────────────────────────────
    if verdict == "needs_clarification":
        return "clarifier"
    if verdict == "not_found":
        return "web_search_fallback"
    return "generator"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(service):
    """
    Nhận RAGService instance, bind tất cả node methods và compile graph.

    Flow:
      router → [rewrite | agent_direct | agent_reject]
    rewrite → [cache_check | retriever]
    cache_check → [generator_cached | retriever]
      retriever → reflector → [generator | clarifier | web_search_fallback]
      web_search_fallback → generator
    """
    import types

    # Import node functions (Option B — standalone functions)
    from app.nodes.router import _node_router
    from app.nodes.rewrite import _node_rewrite
    from app.nodes.retriever import _node_retriever
    from app.nodes.reflector import _node_reflector
    from app.nodes.generator import _node_generator
    from app.nodes.cache import _node_cache_check, _node_generator_cached
    from app.nodes.agent import _node_agent_direct, _node_agent_reject, _node_clarifier
    from app.nodes.web_search import _node_web_search_fallback

    # Bind tất cả node functions vào service instance (Option B)
    bound_router            = types.MethodType(_node_router, service)
    bound_rewrite           = types.MethodType(_node_rewrite, service)
    bound_retriever         = types.MethodType(_node_retriever, service)
    bound_reflector         = types.MethodType(_node_reflector, service)
    bound_generator         = types.MethodType(_node_generator, service)
    bound_cache_check       = types.MethodType(_node_cache_check, service)
    bound_generator_cached  = types.MethodType(_node_generator_cached, service)
    bound_agent_direct      = types.MethodType(_node_agent_direct, service)
    bound_agent_reject      = types.MethodType(_node_agent_reject, service)
    bound_clarifier         = types.MethodType(_node_clarifier, service)
    bound_web_search        = types.MethodType(_node_web_search_fallback, service)

    graph = StateGraph(RAGState)

    # Add nodes
    graph.add_node("router",              bound_router)
    graph.add_node("rewrite",             bound_rewrite)
    graph.add_node("cache_check",         bound_cache_check)
    graph.add_node("generator_cached",    bound_generator_cached)
    graph.add_node("agent_direct",        bound_agent_direct)
    graph.add_node("agent_reject",        bound_agent_reject)
    graph.add_node("retriever",           bound_retriever)
    graph.add_node("reflector",           bound_reflector)
    graph.add_node("clarifier",           bound_clarifier)
    graph.add_node("web_search_fallback", bound_web_search)
    graph.add_node("generator",           bound_generator)

    # Add edges
    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "agent_direct": "agent_direct",
            "rewrite":      "rewrite",
            "agent_reject": "agent_reject",
        },
    )
    graph.add_edge("agent_direct", END)
    graph.add_edge("agent_reject", END)
    graph.add_conditional_edges(
        "rewrite",
        _route_after_rewrite,
        {
            "cache_check": "cache_check",
            "retriever":   "retriever",
        },
    )
    graph.add_conditional_edges(
        "cache_check",
        _route_after_cache,
        {
            "generator_cached": "generator_cached",
            "retriever":        "retriever",
        },
    )
    graph.add_edge("generator_cached", END)
    graph.add_edge("retriever", "reflector")
    graph.add_conditional_edges(
        "reflector",
        _route_after_reflector,
        {
            "generator":           "generator",
            "clarifier":           "clarifier",
            "web_search_fallback": "web_search_fallback",
        },
    )
    graph.add_edge("clarifier",           END)
    graph.add_edge("web_search_fallback", "generator")
    graph.add_edge("generator",           END)

    compiled = graph.compile(checkpointer=service._checkpointer)
    cache_status = "có cache" if service._cache and service._cache.is_connected else "không cache"
    if service._checkpointer:
        logging.info(
            f"✅ LangGraph compiled ({cache_status}) — "
            f"Pipeline: Router→Rewrite→Cache→Retriever→Reflector→Generator."
        )
    else:
        logging.warning(
            f"⚠️  LangGraph compiled (stateless, {cache_status}) — "
            f"Pipeline: Router→Rewrite→Cache→Retriever→Reflector→Generator."
        )
    return compiled
