"""
nodes/cache.py
──────────────
Semantic Cache nodes:
  - _node_cache_check      : kiểm tra cache sau rewrite, trước retriever
  - _node_generator_cached : emit cached response trực tiếp (skip LLM)

Option B: cả hai hàm nhận `self` (RAGService) làm tham số đầu tiên.
"""

import logging

from langchain_core.messages import AIMessage


async def _node_cache_check(self, state: dict, config: dict = None) -> dict:
    """
    Kiểm tra Semantic Cache sau khi rewrite đã bóc tách entities.

    Dùng legal_query (đã chuẩn hóa) làm input tìm kiếm cache.
    Nếu HIT → set cache_hit=True, cached_response=response text.
    Nếu MISS → set cache_hit=False, pipeline tiếp tục bình thường.

    Ưu tiên nguồn enable_cache:
      1. config["configurable"]["enable_cache"]  ← cao nhất (eval path)
      2. state["enable_cache"]                   ← từ router node
      3. True (default — production)
    """
    legal_query = state.get("legal_query", "")
    entities = state.get("entities", {})

    # Config từ LangGraph.invoke() có precedence cao nhất — đảm bảo eval
    # luôn force MISS dù state cũ (checkpointer) có enable_cache=True
    enable_cache_from_config: bool | None = None
    if config and "configurable" in config:
        enable_cache_from_config = config["configurable"].get("enable_cache")

    if enable_cache_from_config is not None:
        enable_cache = bool(enable_cache_from_config)
    else:
        enable_cache = state.get("enable_cache", True)

    if not enable_cache:
        source = "config" if enable_cache_from_config is not None else "state"
        logging.info(f"[STEP1.5] Cache DISABLED (source={source}) → force MISS")
        return {"cache_hit": False, "cached_response": ""}

    if not self._cache or not self._cache.is_connected or not legal_query:
        return {"cache_hit": False, "cached_response": ""}

    try:
        vehicle_type = entities.get("vehicle_type", "") or ""
        violation = entities.get("violation", "") or ""

        result = await self._cache.check(
            query=legal_query,
            vehicle_type=vehicle_type,
            violation_type=violation,
        )

        if result:
            logging.info(
                f"[STEP1.5] Cache HIT ⚡ — distance={result['distance']:.4f}, "
                f"cached_query='{result.get('cached_query', '')[:50]}'"
            )
            return {
                "cache_hit": True,
                "cached_response": result["response"],
            }
        else:
            logging.info(f"[STEP1.5] Cache MISS — query='{legal_query[:60]}'")
            return {"cache_hit": False, "cached_response": ""}

    except Exception as e:
        logging.warning(f"[STEP1.5] Cache check error: {e} — fallback to retriever")
        return {"cache_hit": False, "cached_response": ""}


async def _node_generator_cached(self, state: dict) -> dict:
    """Emit cached response trực tiếp, không cần gọi LLM."""
    cached_response = state.get("cached_response", "")
    return {"messages": [AIMessage(content=cached_response)]}
