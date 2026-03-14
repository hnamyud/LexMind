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
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.tools.graph_retrieval import make_graph_retrieval_tool
from app.tools.web_search import make_web_search_tool

from app.core.config import settings
from app.core.state import RAGState

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ---------------------------------------------------------------------------
# Fallback detection: các mẫu cho thấy agent thiếu thông tin
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pipeline step tracking
# ---------------------------------------------------------------------------

_NODE_STEPS: dict = {
    "router_rewrite":      {"step": 1, "label": "🔍 Đang phân tích câu hỏi..."},
    "retriever":           {"step": 2, "label": "📚 Đang tra cứu đồ thị luật..."},
    "reflector":           {"step": 3, "label": "🔎 Đang kiểm tra tính đầy đủ..."},
    "web_search_fallback": {"step": 3, "label": "🌐 Đang tìm kiếm bổ sung trên web..."},
    "clarifier":           {"step": 3, "label": "❓ Cần làm rõ thêm câu hỏi..."},
    "generator":           {"step": 4, "label": "✍️ Đang soạn câu trả lời..."},
    "agent_direct":        {"step": 1, "label": "💬 Đang xử lý câu hỏi..."},
    "agent_reject":        {"step": 1, "label": "🚫 Đang từ chối câu hỏi ngoại lệ..."},
}

# Chỉ stream thinking/answer từ các node gọi LLM để sinh câu trả lời cuối
_STREAM_NODES: frozenset = frozenset({"generator", "agent_direct"})


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
        self._api_key_vertex = settings.VERTEX_AI_API_KEY
        self._api_key_serper = settings.SERPER_API_KEY
        self._api_key_firecrawl = settings.FIRECRAWL_API_KEY
        self._embed_model_id = settings.EMBED_MODEL_ID

        self._driver = None
        self._llm = None
        self._llm_router = None
        self._embed_model = None

        self._checkpointer: Optional[AsyncPostgresSaver] = checkpointer
        self._graph = None
        self._tools: Optional[List[BaseTool]] = None
        self._system_prompt: str = _load_prompt("synthesis_openai.yaml")
        self._router_rewrite_prompt: str = _load_prompt("router_rewrite.yaml")
        self._reflector_prompt: str = _load_prompt("reflector.yaml")

    async def initialize(self):
        loop = asyncio.get_running_loop()
        await self._connect_neo4j()
        self._connect_llm()
        await loop.run_in_executor(None, self._load_embed_model)
        self._tools = self._create_tools()

        # Validate dependencies
        if not self._driver:
            raise RuntimeError("Khởi tạo RAGService thất bại: Lỗi kết nối Neo4j.")
        if not self._llm or not self._llm_router:
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
            # self._llm = ChatGoogleGenerativeAI(
            #     model="gemini-3-flash-preview",
            #     google_api_key=self._api_key,
            #     temperature=0,
            #     include_thoughts=True,
            #     thinking_budget=8192,
            # )

            self._llm = ChatOpenAI(
                model="free/kimi-k2-0905",
                api_key=self._api_key_vertex,
                base_url="https://vertex-key.com/api/v1",
                temperature=0
            )

            self._llm_router = ChatGoogleGenerativeAI(
                model="gemini-3.1-flash-lite-preview",
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
    # Step 1 — Router + Extractor
    # ------------------------------------------------------------------

    async def _node_router_rewrite(self, state: RAGState) -> dict:
        """
        Step 1: Phân loại câu hỏi (route) + chuẩn hóa thuật ngữ (legal_query)
        + bóc tách entities — tất cả trong 1 lần gọi LLM.
        """
        messages = list(state.get("messages", []))
        
        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
        recent_msgs = chat_msgs[-5:]  # Lấy 5 tin nhắn gần đây nhất (cả Hỏi và Đáp) làm ngữ cảnh
        
        if not recent_msgs:
            return {"route": "direct_answer", "legal_query": "", "entities": {}}
            
        # Lấy câu hỏi cuối cùng của user
        last_question = ""
        for m in reversed(recent_msgs):
            if isinstance(m, HumanMessage):
                last_question = m.content if isinstance(m.content, str) else str(m.content)
                break
                
        if not last_question:
            return {"route": "direct_answer", "legal_query": "", "entities": {}}

        # Định dạng ngữ cảnh từ lịch sử gần nhất để Router hiểu ý câu hỏi nối tiếp
        history_text = "\n".join([f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}" for m in recent_msgs])
        
        question = f"--- Lịch sử chat gần đây ---\n{history_text}\n--- Câu hỏi hiện tại ---\nUser: {last_question}"

        prompt = self._router_rewrite_prompt.format(question=question)
        try:
            response = await self._llm_router.ainvoke([HumanMessage(content=prompt)])
            raw = _extract_ai_text(response).strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw.strip())
            data = json.loads(raw)
            route = data.get("route", "use_tool")
            legal_query = data.get("legal_query", "")
            entities = data.get("entities", {})
            logging.info(f"[STEP1] route={route!r}, legal_query={legal_query!r}, entities={entities}")
            return {"route": route, "legal_query": legal_query, "entities": entities}
        except Exception as e:
            logging.error(f"[STEP1] Lỗi: {e} — fallback use_tool")
            return {"route": "use_tool", "legal_query": question, "entities": {}}

    # ------------------------------------------------------------------
    # Step 2 — Retriever (no LLM call)
    # ------------------------------------------------------------------

    async def _node_retriever(self, state: RAGState) -> dict:
        """
        Step 2: Dùng legal_query embed + truy vấn Neo4j trực tiếp.
        Không gọi LLM — kết quả lưu vào state["context"].
        """
        legal_query = state.get("legal_query", "")
        if not legal_query:
            return {"context": ""}

        graph_tool = next((t for t in self._tools if t.name == "search_legal_graph"), None)
        if not graph_tool:
            logging.error("[STEP2] GraphRetrievalTool không khả dụng.")
            return {"context": ""}

        logging.info(f"[STEP2] Truy vấn Neo4j: {legal_query[:80]}")
        try:
            context = await graph_tool._arun(query=legal_query)
            return {"context": context}
        except Exception as e:
            logging.error(f"[STEP2] Lỗi: {e}")
            return {"context": ""}

    # ------------------------------------------------------------------
    # Step 3 — Reflector / Critic
    # ------------------------------------------------------------------

    async def _node_reflector(self, state: RAGState) -> dict:
        """
        Step 3: LLM đánh giá context — 3 verdict:
          sufficient          → đủ thông tin, đi đến generator
          needs_clarification → có data nhưng thiếu tham số, hỏi ngược user
          not_found           → không có trong NĐ 168, chuyển sang web search
        """
        messages = state.get("messages", [])
        question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                question = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        context = state.get("context", "")
        entities = state.get("entities", {})

        prompt = self._reflector_prompt.format(
            question=question,
            context=context if context else "(Không tìm được dữ liệu từ đồ thị tri thức)",
            entities=json.dumps(entities, ensure_ascii=False, indent=2),
        )
        try:
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = _extract_ai_text(response).strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw.strip())
            data = json.loads(raw)
            verdict = data.get("verdict", "sufficient")
            clarification_q = data.get("clarification_question", "")
            logging.info(f"[STEP3] verdict={verdict!r}")
            return {"reflection": verdict, "clarification_question": clarification_q}
        except Exception as e:
            logging.error(f"[STEP3] Lỗi: {e} — fallback sufficient")
            return {"reflection": "sufficient", "clarification_question": ""}

    async def _node_clarifier(self, state: RAGState) -> dict:
        """Step 3b: Hỏi ngược user khi context có data nhưng thiếu tham số điều kiện."""
        clarification_q = state.get(
            "clarification_question",
            "Bạn có thể cung cấp thêm thông tin để tôi tư vấn chính xác hơn không?",
        )
        return {"messages": [AIMessage(content=clarification_q)]}

    async def _node_web_search_fallback(self, state: RAGState) -> dict:
        """Step 3c: Tìm kiếm web khi Neo4j không có dữ liệu về hành vi."""
        messages = state.get("messages", [])
        question = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                question = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        if not question:
            return {"context": "(Không xác định được câu hỏi để tìm kiếm web.)"}

        web_tool = next((t for t in self._tools if t.name == "web_search"), None)
        if not web_tool:
            logging.warning("[STEP3c] web_search không khả dụng — thiếu SERPER_API_KEY.")
            return {"context": "(Web search không khả dụng.)"}

        logging.info(f"[STEP3c] Tìm web cho: {question[:80]}")
        try:
            result = await web_tool._arun(query=question)
            return {
                "context": (
                    "⚠️ Thông tin KHÔNG có trong Nghị định 168/2024/NĐ-CP. "
                    "Kết quả bổ sung từ tìm kiếm web:\n\n" + result
                )
            }
        except Exception as e:
            logging.error(f"[STEP3c] Lỗi web search: {e}")
            return {"context": f"Lỗi khi tìm kiếm web: {e}"}

    # ------------------------------------------------------------------
    # Step 4 — Generator
    # ------------------------------------------------------------------

    async def _node_generator(self, state: RAGState) -> dict:
        """
        Step 4: Tổng hợp câu trả lời cuối cùng.
        Context (từ Neo4j hoặc web) được inject vào messages trước khi gọi LLM.
        """
        messages = list(state.get("messages", []))
        context = state.get("context", "")

        # 1. Tách SystemMessage cũ ra khỏi tin nhắn User/AI để không bị cắt xoá
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        # 2. Giữ 10 tin nhắn lịch sử gần nhất (5 lượt chat)
        recent_chat_msgs = chat_msgs[-10:]

        # 3. Ghép lại danh sách messages cho LLM
        messages_to_llm = system_msgs + recent_chat_msgs

        if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
            messages_to_llm = [SystemMessage(content=self._system_prompt)] + messages_to_llm

        if context:
            messages_to_llm = messages_to_llm + [
                SystemMessage(
                    content=(
                        "[RETRIEVED_CONTEXT]\n"
                        f"{context}\n"
                        "[/RETRIEVED_CONTEXT]\n\n"
                        "Dùng context trên để trả lời. "
                        "Trích dẫn cụ thể Điểm, Khoản, Điều trong Nghị định 168/2024/NĐ-CP."
                    )
                )
            ]

        try:
            response = await self._llm.ainvoke(messages_to_llm)
            return {"messages": [response]}
        except Exception as e:
            logging.error(f"[STEP4] Lỗi: {e}")
            return {"messages": [AIMessage(content=f"Xin lỗi, đã xảy ra lỗi khi soạn câu trả lời: {e}")]}

    # ------------------------------------------------------------------
    # Direct Answer (câu hỏi không cần tra luật)
    # ------------------------------------------------------------------

    async def _node_agent_direct(self, state: RAGState) -> dict:
        """Trả lời trực tiếp cho câu hỏi direct_answer (chào hỏi, hỏi về chatbot, v.v.)"""
        messages = list(state.get("messages", []))
        
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
        recent_chat_msgs = chat_msgs[-10:]

        messages_to_llm = system_msgs + recent_chat_msgs

        if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
            messages_to_llm = [SystemMessage(content=self._system_prompt)] + messages_to_llm

        try:
            response = await self._llm.ainvoke(messages_to_llm)
            return {"messages": [response]}
        except Exception as e:
            logging.error(f"[DIRECT] Lỗi: {e}")
            return {"messages": [AIMessage(content=f"Xin lỗi, đã xảy ra lỗi: {e}")]}

    # ------------------------------------------------------------------
    # Reject Answer (câu hỏi ngoại lệ / rác)
    # ------------------------------------------------------------------

    async def _node_agent_reject(self, state: RAGState) -> dict:
        """Trả lời từ chối cho câu hỏi out_of_domain, sử dụng lý do từ router (legal_query)."""
        legal_query = state.get("legal_query", "")
        reason = legal_query.replace("REJECT:", "").strip() if "REJECT:" in legal_query else "Xin lỗi, tôi chỉ tư vấn các vấn đề nằm trong phạm vi Luật Giao thông (Nghị định 168/2024/NĐ-CP)."
        if not reason:
            reason = "Xin lỗi, tôi chỉ tư vấn các vấn đề nằm trong phạm vi Luật Giao thông (Nghị định 168/2024/NĐ-CP)."
        return {"messages": [AIMessage(content=reason)]}

    # ------------------------------------------------------------------
    # Routing logic
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_router(state: RAGState) -> str:
        """Step 1 → Step 2 (retriever), direct answer, hoặc reject."""
        route = state.get("route")
        if route == "direct_answer":
            return "agent_direct"
        if route == "out_of_domain":
            return "agent_reject"
        return "retriever"

    @staticmethod
    def _route_after_reflector(state: RAGState) -> str:
        """
        Step 3 → routing:
          sufficient          → generator (Step 4)
          needs_clarification → clarifier (hỏi ngược user, rồi END)
          not_found           → web_search_fallback → generator
        """
        verdict = state.get("reflection", "sufficient")
        if verdict == "needs_clarification":
            return "clarifier"
        if verdict == "not_found":
            return "web_search_fallback"
        return "generator"

    # ------------------------------------------------------------------
    # Build Graph
    # ------------------------------------------------------------------

    def _build_graph(self):
        """
        Pipeline 4 bước:

             [START]
                │
          [router_rewrite]          ← Step 1: Phân loại + Bóc tách entities
                │
         ┌──────┴──────────────┬────────────────┐
         │                     │                │
   direct_answer?          use_tool?      out_of_domain?
         │                     │                │
   [agent_direct]         [retriever]     [agent_reject]
         │                     │                │
        END              [reflector]           END
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        sufficient?  needs_clarification?  not_found?
              │                │                │
         [generator]      [clarifier]   [web_search_fallback]
              │                │                │
             END              END          [generator]  ← Step 4
                                                │
                                               END
        """
        graph = StateGraph(RAGState)

        # Nodes
        graph.add_node("router_rewrite", self._node_router_rewrite)
        graph.add_node("agent_direct", self._node_agent_direct)
        graph.add_node("agent_reject", self._node_agent_reject)
        graph.add_node("retriever", self._node_retriever)
        graph.add_node("reflector", self._node_reflector)
        graph.add_node("clarifier", self._node_clarifier)
        graph.add_node("web_search_fallback", self._node_web_search_fallback)
        graph.add_node("generator", self._node_generator)

        # Edges
        graph.set_entry_point("router_rewrite")
        graph.add_conditional_edges(
            "router_rewrite",
            self._route_after_router,
            {
                "agent_direct": "agent_direct",
                "retriever": "retriever",
                "agent_reject": "agent_reject"
            },
        )
        graph.add_edge("agent_direct", END)
        graph.add_edge("agent_reject", END)
        graph.add_edge("retriever", "reflector")
        graph.add_conditional_edges(
            "reflector",
            self._route_after_reflector,
            {
                "generator": "generator",
                "clarifier": "clarifier",
                "web_search_fallback": "web_search_fallback",
            },
        )
        graph.add_edge("clarifier", END)
        graph.add_edge("web_search_fallback", "generator")
        graph.add_edge("generator", END)

        compiled = graph.compile(checkpointer=self._checkpointer)
        if self._checkpointer:
            logging.info("✅ LangGraph compiled — Pipeline 4 bước: Router→Retriever→Reflector→Generator.")
        else:
            logging.warning("⚠️  LangGraph compiled (stateless) — Pipeline 4 bước: Router→Retriever→Reflector→Generator.")
        return compiled

    # ------------------------------------------------------------------
    # Source extraction helpers
    # ------------------------------------------------------------------

    _RE_GRAPH_SOURCE = re.compile(
        r"---\s*Nguồn\s+(\S+)\s*\(độ tương đồng:\s*([\d.]+)\)\s*---"
    )
    _RE_WEB_URL = re.compile(r"^URL\s*:\s*(https?://\S+)", re.MULTILINE)

    @staticmethod
    def _extract_graph_sources(context: str) -> list[dict]:
        return [
            {"type": "knowledge_graph", "id": m.group(1), "score": float(m.group(2))}
            for m in RAGService._RE_GRAPH_SOURCE.finditer(context)
        ]

    @staticmethod
    def _extract_web_sources(context: str) -> list[dict]:
        return [
            {"type": "web", "url": m.group(1)}
            for m in RAGService._RE_WEB_URL.finditer(context)
        ]

    # ------------------------------------------------------------------
    # Pipeline streaming (LangGraph astream_events v2)
    # ------------------------------------------------------------------

    async def ask_stream(self, question: str, conversation_id: str | None = None):
        initial_state: dict = {
            "messages": [HumanMessage(content=question)],
        }

        thread_id = conversation_id or "default"
        graph_config = {"configurable": {"thread_id": thread_id}}
        collected_sources: list[dict] = []

        # Buffer để parse thẻ <thinking> từ chuỗi văn bản của Kimi
        tag_buffer = ""
        is_thinking = False
        tag_start = "<thinking>"
        tag_end = "</thinking>"

        try:
            async for event in self._graph.astream_events(initial_state, config=graph_config, version="v2"):
                evt_type = event["event"]
                evt_name = event.get("name", "")
                evt_meta_node = event.get("metadata", {}).get("langgraph_node", "")

                # ── Trạng thái quá trình (Process Tracking) ──────────────
                if evt_type == "on_chain_start" and evt_name == evt_meta_node:
                    if evt_name == "router_rewrite":
                        yield json.dumps({"type": "process", "content": "Phân tích và phân loại câu hỏi..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "retriever":
                        yield json.dumps({"type": "process", "content": "Đang tra cứu cơ sở dữ liệu pháp luật..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "reflector":
                        yield json.dumps({"type": "process", "content": "Đánh giá mức độ phù hợp của dữ liệu tìm được..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "clarifier":
                        yield json.dumps({"type": "process", "content": "Chuẩn bị câu hỏi làm rõ ý người dùng..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "web_search_fallback":
                        yield json.dumps({"type": "process", "content": "Tra cứu bổ sung trên web vì dữ liệu nội bộ chưa đủ..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "generator":
                        yield json.dumps({"type": "process", "content": "Tổng hợp câu trả lời dựa trên ngữ cảnh pháp lý..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "agent_direct":
                        yield json.dumps({"type": "process", "content": "Xử lý hội thoại trực tiếp..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "agent_reject":
                        yield json.dumps({"type": "process", "content": "Từ chối câu hỏi ngoại lệ..."}, ensure_ascii=False) + "\n"

                # ── LLM streaming: chỉ từ generator & agent_direct ──────────
                if evt_type == "on_chat_model_stream" and evt_meta_node in _STREAM_NODES:
                    chunk = event["data"]["chunk"]
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
                        # Logic bóc tách on-the-fly thẻ <thinking> chung cho cả Kimi và Gemini text
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
                                    # Kiểm tra xem có đang bị cắt ngang tag_start ở cuối buffer không
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
                                    # Kiểm tra xem có bị cắt ngang thẻ tag_end không
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

                elif evt_type == "on_chain_end" and evt_name == evt_meta_node:
                    output = event.get("data", {}).get("output", {})

                    # ── Clarifier & Agent Reject: emit nội dung trực tiếp ────────
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
                            if evt_name == "retriever":
                                collected_sources.extend(RAGService._extract_graph_sources(ctx))
                            elif evt_name == "web_search_fallback":
                                collected_sources.extend(RAGService._extract_web_sources(ctx))

        except Exception as e:
            logging.error(f"[LANGGRAPH] thread_id={thread_id} | Lỗi: {e}")
            yield json.dumps(
                {"type": "thought", "content": f"❌ Lỗi trong quá trình xử lý: {e}"},
                ensure_ascii=False,
            ) + "\n"

        yield json.dumps({"type": "metadata", "content": {"sources": collected_sources}}, ensure_ascii=False) + "\n"
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
