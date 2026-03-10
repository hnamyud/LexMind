import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional, List

import yaml
from fastapi import HTTPException
from neo4j import AsyncGraphDatabase, exceptions
import neo4j
from sentence_transformers import SentenceTransformer
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import ToolNode, tools_condition

from app.tools.graph_retrieval import make_graph_retrieval_tool
from app.tools.web_search import make_web_search_tool

from app.core.config import settings
from app.core.state import RAGState

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ---------------------------------------------------------------------------
# Fallback detection: các mẫu cho thấy agent thiếu thông tin
# ---------------------------------------------------------------------------
_MISSING_INFO_PATTERNS = [
    "không tìm thấy",
    "không có thông tin",
    "không có trong",
    "ngoài phạm vi",
    "không đủ thông tin",
    "chưa có dữ liệu",
    "thiếu thông tin",
    "không rõ",
    "chưa được cập nhật",
    "không nằm trong",
]

_FALLBACK_MARKER = "[FALLBACK_WEB_SEARCH]"


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


def _detect_missing_info(messages: list) -> bool:
    """Kiểm tra AIMessage cuối cùng có dấu hiệu thiếu thông tin hay không."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            text = _extract_ai_text(msg).lower()
            return any(p in text for p in _MISSING_INFO_PATTERNS)
    return False


def _fallback_already_done(messages: list) -> bool:
    """Kiểm tra fallback search đã chạy chưa (tránh vòng lặp vô hạn)."""
    return any(
        isinstance(m, SystemMessage) and _FALLBACK_MARKER in (m.content if isinstance(m.content, str) else str(m.content))
        for m in messages
    )

def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["template"]

class RAGService:
    def __init__(self, checkpointer: Optional[AsyncPostgresSaver] = None):
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        self._api_key = settings.GOOGLE_API_KEY
        self._api_key_serper = settings.SERPER_API_KEY
        self._api_key_firecrawl = settings.FIRECRAWL_API_KEY
        self._embed_model_id = settings.EMBED_MODEL_ID

        self._driver = None
        self._llm = None
        self._embed_model = None

        self._checkpointer: Optional[AsyncPostgresSaver] = checkpointer
        self._graph = None
        self._tools: Optional[List[BaseTool]] = None
        self._system_prompt: str = _load_prompt("synthesis.yaml")

    async def initialize(self):
        loop = asyncio.get_running_loop()
        await self._connect_neo4j()
        self._connect_llm()
        await loop.run_in_executor(None, self._load_embed_model)
        self._tools = self._create_tools()

        # Validate dependencies
        if not self._driver:
            raise RuntimeError("Khởi tạo RAGService thất bại: Lỗi kết nối Neo4j.")
        if not self._llm:
            raise RuntimeError("Khởi tạo RAGService thất bại: Lỗi cấu hình LLM (Gemini).")
        if not self._embed_model:
            raise RuntimeError("Khởi tạo RAGService thất bại: Không tải được embedding model.")

        self._graph = self._build_graph()

    async def _connect_neo4j(self):
        try:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                max_connection_pool_size=10,
                connection_acquisition_timeout=30,
                max_connection_lifetime=600,     # tái tạo connection mỗi 10 phút
                keep_alive=True,                 # gửi ping giữ connection sống
            )
            await self._driver.verify_connectivity()
            logging.info("✅ Kết nối Neo4j thành công!")
        except exceptions.AuthError as e:
            logging.error(f"❌ Lỗi xác thực Neo4j: {e}")
            self._driver = None
        except Exception as e:
            logging.error(f"❌ Không thể kết nối Neo4j: {e}")
            self._driver = None

    def _connect_llm(self):
        if not self._api_key:
            logging.error("❌ Thiếu GOOGLE_API_KEY")
            return
        try:
            self._llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=self._api_key,
                temperature=0,
                include_thoughts=True,
                thinking_budget=8192,
            )
            logging.info("✅ Kết nối Gemini API thành công! (ChatGoogleGenerativeAI)")
        except Exception as e:
            logging.error(f"❌ Lỗi cấu hình Gemini API: {e}")

    def _load_embed_model(self):
        try:
            logging.info(f"⏳ Đang tải embedding model {self._embed_model_id}...")
            self._embed_model = SentenceTransformer(self._embed_model_id)
            logging.info(
                f"✅ Embedding model sẵn sàng! "
                f"Số chiều: {self._embed_model.get_sentence_embedding_dimension()}"
            )
        except Exception as e:
            logging.error(f"❌ Lỗi tải embedding model: {e}")
            self._embed_model = None

    # ------------------------------------------------------------------
    # LangGraph Nodes & Graph
    # ------------------------------------------------------------------

    async def _node_agent(self, state: RAGState) -> dict:
        messages = list(state.get("messages", []))

        # Thêm System Prompt (Chỉ thêm nếu chưa có)
        if not any(isinstance(m, SystemMessage) for m in messages):
            sys_msg = SystemMessage(content=self._system_prompt)
            messages = [sys_msg] + messages

        llm_with_tools = self._llm.bind_tools(self._tools)

        try:
            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}
        except Exception as e:
            logging.error(f"[AGENT] Lỗi: {e}")
            err_msg = AIMessage(content=f"Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi: {e}")
            return {"messages": [err_msg]}

    # ------------------------------------------------------------------
    # Fallback Search Node
    # ------------------------------------------------------------------

    async def _node_fallback_search(self, state: RAGState) -> dict:
        """
        Được kích hoạt khi agent trả lời nhưng thiếu thông tin.
        Tự động gọi web_search để bổ sung, rồi trả kết quả dưới dạng
        SystemMessage có marker để agent tổng hợp lại.
        """
        messages = state.get("messages", [])

        # Lấy câu hỏi gốc từ HumanMessage đầu tiên
        question = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                question = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        if not question:
            marker = SystemMessage(content=f"{_FALLBACK_MARKER}\nKhông xác định được câu hỏi gốc.")
            return {"messages": [marker]}

        # Tìm web_search tool
        web_tool = next((t for t in self._tools if t.name == "web_search"), None)
        if not web_tool:
            logging.warning("[FALLBACK] web_search tool không khả dụng — bỏ qua fallback.")
            marker = SystemMessage(content=f"{_FALLBACK_MARKER}\nWeb search không khả dụng.")
            return {"messages": [marker]}

        logging.info(f"[FALLBACK] Đang tìm kiếm bổ sung cho: {question[:80]}")

        try:
            result = await web_tool._arun(query=question)
        except Exception as e:
            logging.error(f"[FALLBACK] Lỗi web search: {e}")
            result = f"Lỗi khi tìm kiếm bổ sung: {e}"

        fallback_msg = SystemMessage(
            content=(
                f"{_FALLBACK_MARKER}\n"
                f"Thông tin bổ sung từ tìm kiếm web (fallback tự động):\n\n"
                f"{result}\n\n"
                f"Hãy kết hợp thông tin bổ sung ở trên với dữ liệu đã có từ Knowledge Graph "
                f"để trả lời ĐẦY ĐỦ câu hỏi của người dùng. "
                f"Nếu có mâu thuẫn, ưu tiên nguồn chính thức (vanban.chinhphu.vn, moj.gov.vn)."
            )
        )
        return {"messages": [fallback_msg]}

    # ------------------------------------------------------------------
    # Routing logic
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_agent(state: RAGState) -> str:
        """
        Quyết định bước tiếp theo sau agent node:
          - Có tool_calls        → "tools"  (ReAct loop)
          - Thiếu thông tin      → "fallback_search"  (bổ sung từ web)
          - Đủ thông tin / done  → END
        """
        messages = state.get("messages", [])
        last = messages[-1] if messages else None

        # Agent muốn gọi tool → chuyển sang tool node (ReAct loop)
        if last and hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"

        # Agent đã trả lời xong — kiểm tra thiếu thông tin
        if _detect_missing_info(messages) and not _fallback_already_done(messages):
            return "fallback_search"

        return END

    # ------------------------------------------------------------------
    # Build Graph
    # ------------------------------------------------------------------

    def _build_graph(self):
        """
        Sơ đồ luồng:
             [START]
                │
             [agent] ◄────────────────┐
                │                     │
           ┌────┴─────────┐           │
           │              │           │
      tool_calls?   missing_info?     │
           │              │           │
        [tools]   [fallback_search]   │
           │              │           │
           └──────────────┴───────────┘
                  │
               [agent]
                  │
               [END]
        """
        graph = StateGraph(RAGState)

        # Nodes
        graph.add_node("agent", self._node_agent)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_node("fallback_search", self._node_fallback_search)

        # Edges
        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {"tools": "tools", "fallback_search": "fallback_search", END: END},
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("fallback_search", "agent")  # agent tổng hợp lại sau fallback

        compiled = graph.compile(checkpointer=self._checkpointer)
        if self._checkpointer:
            logging.info("✅ LangGraph compiled với AsyncPostgresSaver (có memory) — ReAct + Fallback.")
        else:
            logging.warning("⚠️  LangGraph compiled KHÔNG có checkpointer (stateless) — ReAct + Fallback.")
        return compiled

    # ------------------------------------------------------------------
    # Source extraction helpers
    # ------------------------------------------------------------------

    _RE_GRAPH_SOURCE = re.compile(
        r"---\s*Nguồn\s+(\S+)\s*\(độ tương đồng:\s*([\d.]+)\)\s*---"
    )
    _RE_WEB_URL = re.compile(r"^URL\s*:\s*(https?://\S+)", re.MULTILINE)

    @staticmethod
    def _extract_sources_from_tool(tool_name: str, output: str) -> list[dict]:
        """Parse tool output text thành danh sách source có cấu trúc."""
        sources: list[dict] = []

        if tool_name == "search_legal_graph":
            for m in RAGService._RE_GRAPH_SOURCE.finditer(output):
                sources.append({
                    "type": "knowledge_graph",
                    "id": m.group(1),
                    "score": float(m.group(2)),
                })

        elif tool_name == "web_search":
            for m in RAGService._RE_WEB_URL.finditer(output):
                sources.append({
                    "type": "web",
                    "url": m.group(1),
                })

        return sources

    # ------------------------------------------------------------------
    # Pipeline streaming (LangGraph)
    # ------------------------------------------------------------------

    async def ask_stream(self, question: str, conversation_id: str | None = None):
        initial_state: dict = {
            "messages": [HumanMessage(content=question)],
        }

        thread_id = conversation_id or "default"
        graph_config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        collected_sources: list[dict] = []
        tool_calls_count = 0

        try:
            # Dùng astream_events version v2 thay cho Queue thủ công
            async for event in self._graph.astream_events(initial_state, config=graph_config, version="v2"):
                evt_type = event["event"]

                if evt_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    content = getattr(chunk, "content", None)
                    if not content:
                        continue

                    # Thinking chunk: content là list [{"type": "thinking", "thinking": "..."}]
                    if isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "thinking" and item.get("thinking"):
                                msg = {"type": "thinking", "content": item["thinking"]}
                                yield json.dumps(msg, ensure_ascii=False) + "\n"
                            elif item.get("type") == "text" and item.get("text"):
                                msg = {"type": "answer", "content": item["text"]}
                                yield json.dumps(msg, ensure_ascii=False) + "\n"
                    # Answer chunk: content là str
                    elif isinstance(content, str) and content:
                        msg = {"type": "answer", "content": content}
                        yield json.dumps(msg, ensure_ascii=False) + "\n"

                elif evt_type == "on_tool_start":
                    tool_calls_count += 1
                    tool_name = event["name"]
                    msg = {"type": "thought", "content": f"🛠️ Đang tra cứu thông tin qua công cụ '{tool_name}'..."}
                    yield json.dumps(msg, ensure_ascii=False) + "\n"

                elif evt_type == "on_tool_end":
                    tool_name = event["name"]
                    msg = {"type": "thought", "content": f"✅ Hoàn tất công cụ '{tool_name}'."}
                    yield json.dumps(msg, ensure_ascii=False) + "\n"

                    # Extract sources từ tool output
                    tool_output = event.get("data", {}).get("output", "")
                    if isinstance(tool_output, str) and tool_output:
                        new_sources = self._extract_sources_from_tool(tool_name, tool_output)
                        collected_sources.extend(new_sources)

        except Exception as e:
            logging.error(f"[LANGGRAPH] thread_id={thread_id} | Lỗi: {e}")
            msg = {"type": "thought", "content": f"❌ Lỗi trong quá trình xử lý: {e}"}
            yield json.dumps(msg, ensure_ascii=False) + "\n"

        # Emit metadata với sources thực tế
        meta_msg = {
            "type": "metadata",
            "content": {
                "sources": collected_sources,
                "tool_calls": tool_calls_count,
            },
        }
        yield json.dumps(meta_msg, ensure_ascii=False) + "\n"

        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    # ------------------------------------------------------------------
    # Tools (dùng cho agentic flow)
    # ------------------------------------------------------------------

    def _create_tools(self) -> List[BaseTool]:
        """Tạo danh sách tools 1 lần khi initialize, tái sử dụng trong suốt vòng đời."""
        tools: List[BaseTool] = [
            make_graph_retrieval_tool(
                driver=self._driver,
                embed_model=self._embed_model,
                top_k=5,
            )
        ]

        if self._api_key_serper:
            tools.append(
                make_web_search_tool(
                    serper_api_key=self._api_key_serper,
                    firecrawl_api_key=self._api_key_firecrawl,
                )
            )
        else:
            logging.warning("[RAGService] SERPER_API_KEY chưa được cấu hình — WebSearchTool bị bỏ qua.")

        return tools

    async def close(self):
        if self._driver:
            await self._driver.close()
            logging.info("Đã đóng kết nối Neo4j.")
