"""
graph/streaming.py
──────────────────
Pipeline streaming qua LangGraph astream_events v2.

Chứa:
  - _NODE_STEPS        : dict step number + label cho mỗi node
  - _STREAM_NODES      : frozenset của các node stream thinking/answer
  - _CACHE_STREAM_NODES: frozenset của các node stream từ cache
  - ask_stream()       : async generator chính — event loop + metrics + cache store

Option B: ask_stream nhận `self` (RAGService) làm tham số đầu tiên.
"""

import asyncio
import json
import logging
import time

from langchain_core.messages import HumanMessage, AIMessage

from app.nodes.base import _extract_ai_text
from app.services.source_parser import (
    parse_legal_anchors,
    extract_graph_sources,
    extract_web_sources,
)
from app.services.cost_calculator import calculate_cost


# ---------------------------------------------------------------------------
# Pipeline step tracking
# ---------------------------------------------------------------------------

_NODE_STEPS: dict = {
    "router":              {"step": 1, "label": "🔍 Đang phân loại câu hỏi..."},
    "rewrite":             {"step": 1, "label": "✍️ Đang chuẩn hóa thuật ngữ pháp lý..."},
    "cache_check":         {"step": 1, "label": "⚡ Đang kiểm tra cache..."},
    "retriever":           {"step": 2, "label": "📚 Đang tra cứu đồ thị luật..."},
    "reflector":           {"step": 3, "label": "🔎 Đang kiểm tra tính đầy đủ..."},
    "web_search_fallback": {"step": 3, "label": "🌐 Đang tìm kiếm bổ sung trên web..."},
    "clarifier":           {"step": 3, "label": "❓ Cần làm rõ thêm câu hỏi..."},
    "generator":           {"step": 4, "label": "✍️ Đang soạn câu trả lời..."},
    "generator_cached":    {"step": 4, "label": "⚡ Trả lời từ cache..."},
    "agent_direct":        {"step": 1, "label": "💬 Đang xử lý câu hỏi..."},
    "agent_reject":        {"step": 1, "label": "🚫 Đang từ chối câu hỏi ngoại lệ..."},
}

# Chỉ stream thinking/answer từ các node gọi LLM để sinh câu trả lời cuối
_STREAM_NODES: frozenset = frozenset({"generator", "agent_direct"})
_CACHE_STREAM_NODES: frozenset = frozenset({"generator_cached"})


# ---------------------------------------------------------------------------
# Process event messages per node
# ---------------------------------------------------------------------------

_NODE_PROCESS_MESSAGES: dict = {
    "router":              "Phân loại câu hỏi...",
    "rewrite":             "Chuẩn hóa thuật ngữ pháp lý...",
    "retriever":           "Đang tra cứu cơ sở dữ liệu pháp luật...",
    "reflector":           "Đánh giá mức độ phù hợp của dữ liệu tìm được...",
    "clarifier":           "Chuẩn bị câu hỏi làm rõ ý người dùng...",
    "web_search_fallback": "Tra cứu bổ sung trên web vì dữ liệu nội bộ chưa đủ...",
    "generator":           "Tổng hợp câu trả lời dựa trên ngữ cảnh pháp lý...",
    "agent_direct":        "Xử lý hội thoại trực tiếp...",
    "agent_reject":        "Từ chối câu hỏi ngoại lệ...",
    "cache_check":         "⚡ Kiểm tra bộ nhớ đệm ngữ nghĩa...",
    "generator_cached":    "⚡ Phản hồi từ bộ nhớ đệm...",
}


# ---------------------------------------------------------------------------
# ask_stream (Option B — nhận self)
# ---------------------------------------------------------------------------

async def ask_stream(
    self,
    question: str,
    conversation_id: str | None = None,
    enable_web_search: bool = True,
    enable_cache: bool = True,
):
    initial_state: dict = {
        "messages": [HumanMessage(content=question)],
    }

    thread_id = conversation_id or "default"
    logging.info(
        f"[ASK] thread_id={thread_id} | enable_web_search={enable_web_search} | enable_cache={enable_cache}"
    )
    graph_config = {
        "configurable": {
            "thread_id": thread_id,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
        },
        "run_name": f"RAG Pipeline — {question[:50]}",
        "metadata": {
            "conversation_id": conversation_id or "default",
            "thread_id": thread_id,
            "enable_web_search": enable_web_search,
            "enable_cache": enable_cache,
        },
    }
    collected_sources: list[dict] = []

    # Cache tracking
    is_cache_hit = False
    final_answer_text = ""    # Thu thập response text để store vào cache
    final_route = ""          # Route từ router
    final_entities = {}       # Entities từ rewrite
    final_legal_query = ""    # Legal query từ rewrite
    final_verdict = ""        # Reflector verdict (để gate cache store)
    final_context = ""        # Context cuối cùng từ retriever/web_search để trả metadata

    # Buffer để parse thẻ <thinking> từ chuỗi văn bản
    tag_buffer = ""
    is_thinking = False
    tag_start = "<thinking>"
    tag_end = "</thinking>"

    # ── Metrics Tracking ──────────────────────────────────────────────
    start_time = time.time()
    ttft = None               # Time to first token
    first_token_received = False

    # Token tracking
    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0

    # Node timing tracking
    node_timings = {}         # {node_name: duration_ms}
    current_node = None
    current_node_start = None

    # Tool usage
    tool_calls_count = 0
    tool_call_details = []

    # Error tracking
    error_message = None
    error_type = None

    try:
        async for event in self._graph.astream_events(initial_state, config=graph_config, version="v2"):
            evt_type = event["event"]
            evt_name = event.get("name", "")
            evt_meta_node = event.get("metadata", {}).get("langgraph_node", "")

            # ── Trạng thái quá trình (Process Tracking) ──────────────
            if evt_type == "on_chain_start" and evt_name == evt_meta_node:
                current_node = evt_name
                current_node_start = time.time()

                process_msg = _NODE_PROCESS_MESSAGES.get(evt_name)
                if process_msg:
                    yield json.dumps({"type": "process", "content": process_msg}, ensure_ascii=False) + "\n"

            # ── LLM streaming: chỉ từ generator & agent_direct ──────────
            if evt_type == "on_chat_model_stream" and evt_meta_node in _STREAM_NODES:
                chunk = event["data"]["chunk"]

                # Capture TTFT (time to first token)
                if not first_token_received:
                    ttft = int((time.time() - start_time) * 1000)
                    first_token_received = True
                    logging.info(f"[METRICS] TTFT: {ttft}ms")

                content = getattr(chunk, "content", None)
                if not content:
                    continue

                text_to_process = ""

                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        # Xử lý native thoughts của Gemini (nếu có)
                        if item.get("type") == "thinking" and item.get("thinking"):
                            yield json.dumps(
                                {"type": "thinking", "content": item["thinking"]},
                                ensure_ascii=False,
                            ) + "\n"
                        # Gom phần text thường để xử lý tag
                        elif item.get("type") == "text" and item.get("text"):
                            text_to_process += item["text"]
                elif isinstance(content, str):
                    text_to_process += content

                if text_to_process:
                    # Logic bóc tách on-the-fly thẻ <thinking>
                    tag_buffer += text_to_process
                    while tag_buffer:
                        if not is_thinking:
                            if tag_start in tag_buffer:
                                idx = tag_buffer.find(tag_start)
                                if idx > 0:
                                    yield json.dumps({"type": "answer", "content": tag_buffer[:idx]}, ensure_ascii=False) + "\n"
                                is_thinking = True
                                tag_buffer = tag_buffer[idx + len(tag_start):]
                            else:
                                match_idx = -1
                                for i in range(1, len(tag_start)):
                                    if tag_buffer.endswith(tag_start[:i]):
                                        match_idx = len(tag_buffer) - i
                                        break
                                if match_idx != -1:
                                    if match_idx > 0:
                                        yield json.dumps({"type": "answer", "content": tag_buffer[:match_idx]}, ensure_ascii=False) + "\n"
                                    tag_buffer = tag_buffer[match_idx:]
                                    break
                                else:
                                    yield json.dumps({"type": "answer", "content": tag_buffer}, ensure_ascii=False) + "\n"
                                    tag_buffer = ""
                        else:
                            if tag_end in tag_buffer:
                                idx = tag_buffer.find(tag_end)
                                if idx > 0:
                                    yield json.dumps({"type": "thinking", "content": tag_buffer[:idx]}, ensure_ascii=False) + "\n"
                                is_thinking = False
                                tag_buffer = tag_buffer[idx + len(tag_end):]
                            else:
                                match_idx = -1
                                for i in range(1, len(tag_end)):
                                    if tag_buffer.endswith(tag_end[:i]):
                                        match_idx = len(tag_buffer) - i
                                        break
                                if match_idx != -1:
                                    if match_idx > 0:
                                        yield json.dumps({"type": "thinking", "content": tag_buffer[:match_idx]}, ensure_ascii=False) + "\n"
                                    tag_buffer = tag_buffer[match_idx:]
                                    break
                                else:
                                    yield json.dumps({"type": "thinking", "content": tag_buffer}, ensure_ascii=False) + "\n"
                                    tag_buffer = ""

            # ── Capture token usage from on_chat_model_end ──────────────
            elif evt_type == "on_chat_model_end" and evt_meta_node in _STREAM_NODES:
                output_data = event.get("data", {}).get("output", {})

                usage_metadata = None
                if hasattr(output_data, "usage_metadata"):
                    usage_metadata = output_data.usage_metadata
                elif isinstance(output_data, dict):
                    usage_metadata = output_data.get("usage_metadata")

                if usage_metadata:
                    logging.info(f"[METRICS] on_chat_model_end usage_metadata found: {usage_metadata}")

                    if isinstance(usage_metadata, dict):
                        total_input_tokens = usage_metadata.get("input_tokens", 0) or 0
                        total_output_tokens = usage_metadata.get("output_tokens", 0) or 0
                        output_details = usage_metadata.get("output_token_details", {})
                        total_thinking_tokens = output_details.get("reasoning", 0) or 0
                    else:
                        total_input_tokens = getattr(usage_metadata, "input_tokens", 0) or 0
                        total_output_tokens = getattr(usage_metadata, "output_tokens", 0) or 0
                        total_thinking_tokens = getattr(usage_metadata, "thinking_tokens", 0) or 0

                    logging.info(
                        f"[METRICS] Captured tokens - input: {total_input_tokens}, "
                        f"output: {total_output_tokens}, thinking: {total_thinking_tokens}"
                    )
                else:
                    logging.debug(
                        f"[METRICS] on_chat_model_end but no usage_metadata. "
                        f"output type: {type(output_data)}"
                    )

            elif evt_type == "on_chain_end" and evt_name == evt_meta_node:
                # Track node timing
                if current_node == evt_name and current_node_start:
                    duration_ms = int((time.time() - current_node_start) * 1000)
                    node_timings[evt_name] = duration_ms
                    logging.info(f"[METRICS] Node {evt_name}: {duration_ms}ms")

                    if evt_name == "retriever":
                        tool_calls_count += 1
                        tool_call_details.append({"tool": "graph_retrieval", "duration_ms": duration_ms})
                    elif evt_name == "web_search_fallback":
                        tool_calls_count += 1
                        tool_call_details.append({"tool": "web_search", "duration_ms": duration_ms})

                output = event.get("data", {}).get("output", {})

                # ── Emit nội dung trực tiếp cho các node KHÔNG stream ────────
                if evt_name in ("clarifier", "agent_reject"):
                    for m in (output.get("messages", []) if isinstance(output, dict) else []):
                        if isinstance(m, AIMessage):
                            text = _extract_ai_text(m)
                            if text:
                                yield json.dumps({"type": "answer", "content": text}, ensure_ascii=False) + "\n"

                # ── Source collection ────────────────────────────────────
                elif isinstance(output, dict):
                    ctx = output.get("context", "")
                    if ctx and isinstance(ctx, str):
                        final_context = ctx
                        if evt_name == "retriever":
                            collected_sources.extend(extract_graph_sources(ctx))
                            anchors = parse_legal_anchors(ctx)
                            if anchors:
                                for anchor in anchors[:3]:
                                    yield json.dumps(
                                        {"type": "process", "content": f"📖 Đang tham khảo: {anchor}"},
                                        ensure_ascii=False,
                                    ) + "\n"
                        elif evt_name == "web_search_fallback":
                            ws = output.get("web_sources", [])
                            if ws:
                                collected_sources.extend(
                                    {"type": "web", "url": s["url"], "title": s.get("title", "")}
                                    for s in ws
                                )
                            else:
                                collected_sources.extend(extract_web_sources(ctx))

                # ── Cache: capture answer text from generator for store ──
                if evt_name == "generator" and isinstance(output, dict):
                    for m in (output.get("messages", []) if isinstance(output, dict) else []):
                        if isinstance(m, AIMessage):
                            text = _extract_ai_text(m)
                            if text:
                                final_answer_text = text

                # ── Cache: track route/entities từ router + rewrite ───────
                if isinstance(output, dict):
                    if evt_name == "router":
                        final_route = output.get("route", "")
                    elif evt_name == "rewrite":
                        final_entities = output.get("entities", {})
                        final_legal_query = output.get("legal_query", "")
                    elif evt_name == "cache_check":
                        is_cache_hit = output.get("cache_hit", False)
                    elif evt_name == "reflector":
                        final_verdict = output.get("reflection", "")

                # ── generator_cached: emit cached response trực tiếp ─────
                if evt_name == "generator_cached" and isinstance(output, dict):
                    for m in (output.get("messages", []) if isinstance(output, dict) else []):
                        if isinstance(m, AIMessage):
                            text = _extract_ai_text(m)
                            if text:
                                final_answer_text = text
                                yield json.dumps({"type": "answer", "content": text}, ensure_ascii=False) + "\n"

    except Exception as e:
        error_message = str(e)
        error_type = type(e).__name__
        logging.error(f"[LANGGRAPH] thread_id={thread_id} | Lỗi: {e}")
        yield json.dumps(
            {"type": "thought", "content": f"❌ Lỗi trong quá trình xử lý: {e}"},
            ensure_ascii=False,
        ) + "\n"

    # ── Calculate metrics ──────────────────────────────────────────────
    total_time_ms = int((time.time() - start_time) * 1000)

    cost = calculate_cost(
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        thinking_tokens=total_thinking_tokens,
    )

    metrics = {
        "model": "gemini-3-flash-preview",
        "ttft": ttft,
        "totalTime": total_time_ms,
        "graphQueryTime": node_timings.get("retriever"),
        "webSearchTime": node_timings.get("web_search_fallback"),
        "cacheCheckTime": node_timings.get("cache_check"),
        "cacheHit": is_cache_hit,
        "inputTokens": total_input_tokens if total_input_tokens > 0 else None,
        "outputTokens": total_output_tokens if total_output_tokens > 0 else None,
        "thinkingTokens": total_thinking_tokens if total_thinking_tokens > 0 else None,
        "toolCalls": tool_calls_count,
        "toolCallDetails": tool_call_details if tool_call_details else None,
        "cost": cost,
        "error": error_message,
        "errorType": error_type,
    }

    node_breakdown = {
        "routerTime":          node_timings.get("router"),
        "rewriteTime":         node_timings.get("rewrite"),
        "cacheCheckTime":      node_timings.get("cache_check"),
        "retrievalTime":       node_timings.get("retriever"),
        "reflectorTime":       node_timings.get("reflector"),
        "generatorTime":       node_timings.get("generator"),
        "generatorCachedTime": node_timings.get("generator_cached"),
        "clarifierTime":       node_timings.get("clarifier"),
        "webSearchTime":       node_timings.get("web_search_fallback"),
    }

    executed_breakdown = {k: v for k, v in node_breakdown.items() if isinstance(v, int)}
    slowest_node = None
    if executed_breakdown:
        slowest_name = max(executed_breakdown, key=executed_breakdown.get)
        slowest_node = {"node": slowest_name, "durationMs": executed_breakdown[slowest_name]}

    metrics["nodeTimings"] = node_breakdown
    metrics["slowestNode"] = slowest_node

    logging.info(f"[METRICS] Final metrics: {metrics}")
    logging.info(f"[METRICS] Node breakdown: {node_breakdown}")
    if slowest_node:
        logging.info(
            f"[METRICS] Slowest node: {slowest_node['node']}="
            f"{slowest_node['durationMs']}ms"
        )

    yield json.dumps({"type": "metrics", "content": metrics}, ensure_ascii=False) + "\n"
    yield json.dumps(
        {
            "type": "metadata",
            "content": {
                "sources": collected_sources,
                "context": final_context,
                "reflector_verdict": final_verdict,
                "cacheHit": is_cache_hit,
                "nodeTimings": node_breakdown,
            },
        },
        ensure_ascii=False,
    ) + "\n"
    yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    # ── Cache Store (fire-and-forget, chỉ khi verdict=sufficient) ─────
    if (
        self._cache
        and self._cache.is_connected
        and enable_cache
        and final_route == "use_tool"
        and not is_cache_hit
        and final_verdict == "sufficient"
        and final_answer_text
        and final_legal_query
        and not error_message
    ):
        async def _store_cache():
            try:
                await self._cache.store(
                    query=final_legal_query,
                    response=final_answer_text,
                    entities=final_entities,
                    metadata={
                        "conversation_id": conversation_id,
                        "sources_count": len(collected_sources),
                    },
                )
            except Exception as e:
                logging.warning(f"[CACHE] Lỗi khi store vào cache: {e}")

        asyncio.create_task(_store_cache())
