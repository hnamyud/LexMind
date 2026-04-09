"""
services/rag_service.py
───────────────────────
RAGService — điểm khởi tạo và lifecycle cho toàn bộ RAG pipeline.

Sau refactor, file này CHỈ còn:
  - __init__()        : cấu hình, load prompts/skills
  - initialize()      : orchestrate async init (Neo4j, LLM, embed, cache, graph)
  - _connect_neo4j()  : kết nối Neo4j driver
  - _create_tools()   : tạo graph + web search tools
  - ask_stream()      : delegate sang graph/streaming.py
  - close()           : dọn dẹp connections

Mọi logic node đã được tách sang:
  app/nodes/    — tất cả node functions
  app/graph/    — builder.py (StateGraph) + streaming.py (ask_stream)
  app/services/ — llm_manager.py, embed_manager.py, source_parser.py, cost_calculator.py
"""

import asyncio
import logging
import types
from typing import Optional, List

from fastapi import HTTPException
from neo4j import AsyncGraphDatabase, exceptions
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.tools import BaseTool

from app.core.config import settings
from app.core.state import RAGState
from app.cache.semantic_cache import SemanticCacheService

from app.nodes.base import _load_prompt, _load_skill
from app.services.llm_manager import connect_llm
from app.services.embed_manager import load_embed_model
from app.graph.builder import build_graph
from app.graph.streaming import ask_stream as _ask_stream_fn
from app.tools.graph_retrieval import make_graph_retrieval_tool
from app.tools.web_search import make_web_search_tool


class RAGService:
    # Threshold dùng trong retriever để lọc context trước khi reflector
    _REFLECTOR_SCORE_THRESHOLD: float = 0.012

    def __init__(self, checkpointer: Optional[AsyncPostgresSaver] = None):
        # ── Config từ settings ──────────────────────────────────────────
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        self._api_key = settings.GOOGLE_API_KEY
        self._llm_router_model = settings.LLM_ROUTER
        self._llm_direct_model = settings.LLM_DIRECT
        self._llm_generator_model = settings.LLM_GENERATOR
        self._llm_reflector_model = settings.LLM_REFLECTOR
        self._api_key_serper = settings.SERPER_API_KEY
        self._api_key_firecrawl = settings.FIRECRAWL_API_KEY
        self._embed_model_id = settings.EMBED_MODEL_ID

        # ── LLM instances (khởi tạo bởi llm_manager.connect_llm) ───────
        self._driver = None
        self._llm_router = None
        self._llm_direct = None  # LLM riêng cho agent_direct (streaming, nhẹ)

        # Generator LLMs theo complexity level
        self._llm_gen_l1 = None  # Level 1 (Simple):  thinking_budget=0
        self._llm_gen_l2 = None  # Level 2 (Medium):  thinking_budget=2048
        self._llm_gen_l3 = None  # Level 3 (Complex): thinking_budget=4096

        # Reflector LLMs theo complexity level (Reflector = Generator / 4)
        self._llm_ref_l2 = None  # Level 2: thinking_budget=512
        self._llm_ref_l3 = None  # Level 3: thinking_budget=1024

        # Alias cho Generator mặc định (Level 1) — backward compat
        self._llm = None
        self._embed_model = None

        # ── Lifecycle ───────────────────────────────────────────────────
        self._checkpointer: Optional[AsyncPostgresSaver] = checkpointer
        self._graph = None
        self._tools: Optional[List[BaseTool]] = None
        self._cache: Optional[SemanticCacheService] = None

        # ── Prompts ─────────────────────────────────────────────────────
        self._system_prompt: str = _load_prompt("synthesis.yaml")
        self._system_prompt_compact: str = _load_prompt("synthesis_compact.yaml")
        self._natural_prompt: str = _load_prompt("synthesis_natural.yaml")
        self._router_classify_prompt: str = _load_prompt("router_classify.yaml")
        self._rewrite_prompt: str = _load_prompt("rewrite.yaml")
        self._reflector_prompt: str = _load_prompt("reflector.yaml")

        # ── Agent skills ─────────────────────────────────────────────────
        self._skill_graph_analyzer: str = _load_skill("01_graph_analyzer.skill.md")
        self._skill_citation_validator: str = _load_skill("02_citation_validator.skill.md")

    # ------------------------------------------------------------------
    # initialize — orchestrate toàn bộ async init
    # ------------------------------------------------------------------

    async def initialize(self):
        loop = asyncio.get_running_loop()
        await self._connect_neo4j()
        connect_llm(self)
        await loop.run_in_executor(None, load_embed_model, self)
        self._tools = self._create_tools()

        # Validate dependencies
        if not self._driver:
            raise RuntimeError("Khởi tạo RAGService thất bại: Lỗi kết nối Neo4j.")
        if not self._llm or not self._llm_router or not self._llm_direct:
            raise RuntimeError("Khởi tạo RAGService thất bại: Lỗi cấu hình LLM (Gemini).")
        if not self._embed_model:
            raise RuntimeError("Khởi tạo RAGService thất bại: Không tải được embedding model.")

        # Khởi tạo Semantic Cache (non-blocking, graceful fallback)
        self._cache = SemanticCacheService(
            redis_url=settings.REDIS_URL,
            embed_model=self._embed_model,
            ttl=86400,  # 24 giờ
        )
        await self._cache.initialize()

        self._graph = build_graph(self)

    # ------------------------------------------------------------------
    # Neo4j connection
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _create_tools(self) -> List[BaseTool]:
        """Tạo danh sách tools 1 lần khi initialize, tái sử dụng trong suốt vòng đời."""
        tools: List[BaseTool] = [
            make_graph_retrieval_tool(
                driver=self._driver,
                embed_model=self._embed_model,
                top_k=5,
                score_threshold=0.010,      # Ngưỡng thấp nhất để chấp nhận kết quả
                # Timeouts for parallel branches
                keyword_timeout=3.0,
                vector_timeout=5.0,
                graph_timeout=5.0,
                consequence_timeout=3.0,    # consequence-first branch
                # RRF threshold
                rrf_threshold=0.016,        # Balanced mode
                # Vehicle-aware boosting
                vehicle_boost_enabled=True,
                vehicle_boost_multiplier=1.3,
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

    # ------------------------------------------------------------------
    # Pipeline entry point (delegate sang graph/streaming.py)
    # ------------------------------------------------------------------

    async def ask_stream(
        self,
        question: str,
        conversation_id: str | None = None,
        enable_web_search: bool = True,
        enable_cache: bool = True,
    ):
        """Streaming pipeline — delegate sang graph/streaming.ask_stream."""
        async for chunk in _ask_stream_fn(
            self,
            question=question,
            conversation_id=conversation_id,
            enable_web_search=enable_web_search,
            enable_cache=enable_cache,
        ):
            yield chunk

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        if self._cache:
            await self._cache.close()
        if self._driver:
            await self._driver.close()
            logging.info("Đã đóng kết nối Neo4j.")
