import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional, List

import yaml
from fastapi import HTTPException
from neo4j import AsyncGraphDatabase, exceptions
from sentence_transformers import SentenceTransformer
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.tools.graph_retrieval import make_graph_retrieval_tool
from app.tools.web_search import make_web_search_tool

from app.core.config import settings
from app.core.state import RAGState
from app.cache.semantic_cache import SemanticCacheService

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SKILLS_DIR = Path(__file__).parent.parent / "agent-skills"


def _load_skill(filename: str) -> str:
    """Load một agent-skill .md file, trả về nội dung text thuần."""
    path = _SKILLS_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logging.warning(f"[SKILL] Không tìm thấy skill file: {filename}")
        return ""

# ---------------------------------------------------------------------------
# Fallback detection: các mẫu cho thấy agent thiếu thông tin
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pipeline step tracking
# ---------------------------------------------------------------------------

_NODE_STEPS: dict = {
    "router_rewrite":      {"step": 1, "label": "🔍 Đang phân tích câu hỏi..."},
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
    _REFLECTOR_SCORE_THRESHOLD: float = 0.012
    _RE_CONTEXT_SOURCE_HEADER = re.compile(
        r"^---\s*Nguồn\s+\S+\s*\(score:\s*([\d.]+)\s*\|[^)]*\)\s*---\s*$",
        re.MULTILINE,
    )

    def __init__(self, checkpointer: Optional[AsyncPostgresSaver] = None):
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        self._api_key = settings.GOOGLE_API_KEY
        self._llm_router_model = settings.LLM_ROUTER
        self._llm_generator_model = settings.LLM_GENERATOR
        self._llm_reflector_model = settings.LLM_REFLECTOR
        self._api_key_serper = settings.SERPER_API_KEY
        self._api_key_firecrawl = settings.FIRECRAWL_API_KEY
        self._embed_model_id = settings.EMBED_MODEL_ID

        self._driver = None
        self._llm_router = None

        # Generator LLMs theo complexity level
        self._llm_gen_l1 = None  # Level 1 (Simple):  thinking_budget=0
        self._llm_gen_l2 = None  # Level 2 (Medium):  thinking_budget=2048
        self._llm_gen_l3 = None  # Level 3 (Complex): thinking_budget=4096

        # Reflector LLMs theo complexity level (Reflector = Generator / 4)
        self._llm_ref_l2 = None  # Level 2: thinking_budget=512
        self._llm_ref_l3 = None  # Level 3: thinking_budget=1024

        # Alias cho Generator mặc định (Level 2) — dùng ở các chỗ gọi _llm trực tiếp
        self._llm = None  # trỏ tới _llm_gen_l2 sau khi khởi tạo
        self._embed_model = None

        self._checkpointer: Optional[AsyncPostgresSaver] = checkpointer
        self._graph = None
        self._tools: Optional[List[BaseTool]] = None
        self._system_prompt: str = _load_prompt("synthesis.yaml")
        self._system_prompt_compact: str = _load_prompt("synthesis_compact.yaml")
        self._natural_prompt: str = _load_prompt("synthesis_natural.yaml")
        self._router_rewrite_prompt: str = _load_prompt("router_rewrite.yaml")
        self._reflector_prompt: str = _load_prompt("reflector.yaml")

        # Agent skills — chỉ load những skill có giá trị bổ sung so với prompts hiện có
        self._skill_graph_analyzer: str = _load_skill("01_graph_analyzer.skill.md")
        self._skill_citation_validator: str = _load_skill("02_citation_validator.skill.md")

        # Semantic Cache
        self._cache: Optional[SemanticCacheService] = None

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

        # Khởi tạo Semantic Cache (non-blocking, graceful fallback)
        self._cache = SemanticCacheService(
            redis_url=settings.REDIS_URL,
            embed_model=self._embed_model,
            ttl=86400,  # 24 giờ
        )
        await self._cache.initialize()

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
            self._llm_router = ChatGoogleGenerativeAI(
                model=self._llm_router_model,
                google_api_key=self._api_key,
                temperature=0,
            )

            # ── Generator LLMs (Complexity Level 1/2/3) ────────────────────────
            # Level 1 — Simple: có thể thinking(rất ít) hoặc không
            self._llm_gen_l1 = ChatGoogleGenerativeAI(
                model=self._llm_generator_model,
                google_api_key=self._api_key,
                temperature=0,
                thinking_level="low",
                include_thoughts=False,  
                streaming=True,
            )
            # Level 2 — Medium: thinking vừa phải
            self._llm_gen_l2 = ChatGoogleGenerativeAI(
                model=self._llm_generator_model,
                google_api_key=self._api_key,
                temperature=0,
                thinking_level="medium",
                include_thoughts=True,
                streaming=True,
            )
            # Level 3 — Complex: full thinking
            self._llm_gen_l3 = ChatGoogleGenerativeAI(
                model=self._llm_generator_model,
                google_api_key=self._api_key,
                temperature=0,               
                thinking_level="high",
                include_thoughts=True,
                streaming=True,
            )

            # ── Reflector LLMs (budget = Generator / 4) ────────────────────────
            # Level 1: Reflector bị tắt hoàn toàn — không cần instance
            # Level 2: 
            self._llm_ref_l2 = ChatGoogleGenerativeAI(
                model=self._llm_reflector_model,
                google_api_key=self._api_key,
                temperature=0,
                thinking_level="low",              
            )
            # Level 3: 
            self._llm_ref_l3 = ChatGoogleGenerativeAI(
                model=self._llm_reflector_model,
                google_api_key=self._api_key,
                temperature=0,
                thinking_level="medium",
            )

            # Alias _llm → _llm_gen_l2 (backward-compat cho agent_direct)
            self._llm = self._llm_gen_l2

            logging.info(
                "✅ Kết nối Gemini API thành công! "
                "(Generator L1/L2/L3 + Reflector L2/L3)"
            )
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

    async def _node_router_rewrite(self, state: RAGState, config: dict = None) -> dict:
        """
        Step 1: Phân loại câu hỏi (route) + chuẩn hóa thuật ngữ (legal_query)
        + bóc tách entities + phân tách đa vi phạm (sub_queries) — tất cả trong 1 lần gọi LLM.

        NOTE: LangGraph truyền `config` vào các *node* (không phải routing function).
        Nên ta đọc enable_web_search tại đây và lưu vào state để routing function đọc sau.
        """
        # Đọc enable_web_search từ config (LangGraph truyền vào node, không phải routing fn)
        enable_web_search = True
        enable_cache = True
        if config and "configurable" in config:
            enable_web_search = config["configurable"].get("enable_web_search", True)
            enable_cache = config["configurable"].get("enable_cache", True)
        logging.info(f"[STEP1] enable_web_search={enable_web_search}")
        logging.info(f"[STEP1] enable_cache={enable_cache}")

        messages = list(state.get("messages", []))

        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
        recent_msgs = chat_msgs[-5:]  # Lấy 5 tin nhắn gần đây nhất (cả Hỏi và Đáp) làm ngữ cảnh

        if not recent_msgs:
            return {"route": "direct_answer", "legal_query": "", "entities": {}, "response_style": "natural", "sub_queries": [], "enable_web_search": enable_web_search, "enable_cache": enable_cache}

        # Lấy câu hỏi cuối cùng của user
        last_question = ""
        for m in reversed(recent_msgs):
            if isinstance(m, HumanMessage):
                last_question = m.content if isinstance(m.content, str) else str(m.content)
                break

        if not last_question:
            return {"route": "direct_answer", "legal_query": "", "entities": {}, "response_style": "natural", "sub_queries": [], "enable_web_search": enable_web_search, "enable_cache": enable_cache}

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

            # ── Gắn tag response_style dựa trên route ──────────────────
            response_style = "legal" if route == "use_tool" else "natural"

            # ── Parse & validate sub_queries (multi-violation) ──────────
            sub_queries = data.get("sub_queries", [])
            validated_subs = []
            for sq in sub_queries[:3]:  # Cap tối đa 3 sub-queries
                if isinstance(sq, dict) and sq.get("legal_query"):
                    validated_subs.append({
                        "legal_query": sq["legal_query"],
                        "entities": sq.get("entities", {}),
                        "label": sq.get("label", sq["legal_query"][:30]),
                    })

            # ── Parse + validate complexity_level ──────────────────────────
            raw_level = data.get("complexity_level", 2)
            try:
                complexity_level = max(1, min(3, int(raw_level)))
            except (TypeError, ValueError):
                complexity_level = 2

            # Auto-upgrade: nhiều sub_queries → luôn là level 3
            if len(validated_subs) >= 2 and complexity_level < 3:
                complexity_level = 3
            # Auto-upgrade: 1 sub_query → tối thiểu level 2
            elif len(validated_subs) == 1 and complexity_level < 2:
                complexity_level = 2

            logging.info(
                f"[STEP1] route={route!r}, style={response_style!r}, "
                f"legal_query={legal_query!r}, sub_queries={len(validated_subs)}, "
                f"complexity_level={complexity_level}"
            )
            return {
                "route": route,
                "legal_query": legal_query,
                "entities": entities,
                "response_style": response_style,
                "sub_queries": validated_subs,
                "complexity_level": complexity_level,
                "enable_web_search": enable_web_search,  # lưu vào state để routing fn đọc
                "enable_cache": enable_cache,
            }
        except Exception as e:
            logging.error(f"[STEP1] Lỗi: {e} — fallback use_tool")
            return {"route": "use_tool", "legal_query": question, "entities": {}, "response_style": "legal", "sub_queries": [], "complexity_level": 2, "enable_web_search": enable_web_search, "enable_cache": enable_cache}

    # ------------------------------------------------------------------
    # Step 2 — Retriever (parallel multi-violation via asyncio.gather)
    # ------------------------------------------------------------------


    @classmethod
    def _filter_context_for_reflector(cls, context: str) -> str:
        """
        Lọc block context trước khi chuyển sang reflector:
        - Chỉ giữ các block có score >= _REFLECTOR_SCORE_THRESHOLD
        - Nếu tất cả block bị loại -> trả marker LOW_CONFIDENCE để trigger web search.
        """
        if not context:
            return context

        # Tôn trọng kết quả đã được graph tool đánh dấu low-confidence trước đó.
        if "[LOW_CONFIDENCE_THRESHOLD]" in context:
            return context

        headers = list(cls._RE_CONTEXT_SOURCE_HEADER.finditer(context))
        if not headers:
            return context

        kept_blocks: list[str] = []
        total_blocks = len(headers)

        for i, header in enumerate(headers):
            start = header.start()
            end = headers[i + 1].start() if i + 1 < total_blocks else len(context)
            block = context[start:end].strip()
            try:
                score = float(header.group(1))
            except Exception:
                score = 0.0

            if score >= cls._REFLECTOR_SCORE_THRESHOLD:
                kept_blocks.append(block)

        if not kept_blocks:
            low_confidence_msg = (
                "⚠️ [LOW_CONFIDENCE_THRESHOLD] "
                f"Tất cả kết quả retrieval đều dưới ngưỡng {cls._REFLECTOR_SCORE_THRESHOLD:.1f}. "
                "Nên chuyển sang tìm kiếm web để bổ sung."
            )
            logging.warning(
                f"[STEP2] Pre-reflector threshold filter removed all blocks: "
                f"kept=0/{total_blocks}, threshold={cls._REFLECTOR_SCORE_THRESHOLD:.1f}"
            )
            return low_confidence_msg

        filtered_context = "\n\n".join(kept_blocks)
        if len(kept_blocks) < total_blocks:
            logging.info(
                f"[STEP2] Pre-reflector threshold filter: kept={len(kept_blocks)}/{total_blocks}, "
                f"threshold={cls._REFLECTOR_SCORE_THRESHOLD:.1f}"
            )

        return filtered_context

    async def _node_retriever(self, state: RAGState) -> dict:
        """
        Step 2: Retrieval — xử lý cả single-violation và multi-violation.

        - Single violation (sub_queries rỗng): chạy 1 lần _arun() như cũ
        - Multi-violation (sub_queries không rỗng): chạy song song N lần
          _arun() qua asyncio.gather, rồi gộp kết quả có cấu trúc
        """
        sub_queries = state.get("sub_queries", [])
        legal_query = state.get("legal_query", "")
        entities = state.get("entities", {})

        graph_tool = next((t for t in self._tools if t.name == "search_legal_graph"), None)
        if not graph_tool:
            logging.error("[STEP2] GraphRetrievalTool không khả dụng.")
            return {"context": "", "sub_contexts": []}

        # ── Single-violation path (backward compatible) ───────────────
        if not sub_queries:
            if not legal_query:
                return {"context": "", "sub_contexts": []}

            logging.info(
                f"[STEP2] Single-query retrieval: query='{legal_query[:80]}' | "
                f"entities={entities}"
            )
            try:
                context = await graph_tool._arun(query=legal_query, entities=entities)
                context = self._filter_context_for_reflector(context)
                return {"context": context, "sub_contexts": []}
            except Exception as e:
                logging.error(f"[STEP2] Lỗi: {e}")
                return {"context": "", "sub_contexts": []}

        # ── Multi-violation path (parallel retrieval) ─────────────────
        logging.info(
            f"[STEP2] Multi-query parallel retrieval: "
            f"{len(sub_queries)} sub-queries"
        )

        async def _retrieve_one(sq: dict) -> dict:
            q = sq.get("legal_query", "")
            e = sq.get("entities", {})
            label = sq.get("label", q[:30])
            if not q:
                return {"legal_query": q, "context": "", "label": label}
            try:
                ctx = await graph_tool._arun(query=q, entities=e)
                ctx = self._filter_context_for_reflector(ctx)
                return {"legal_query": q, "context": ctx, "label": label}
            except Exception as ex:
                logging.error(f"[STEP2] Sub-query '{label}' error: {ex}")
                return {"legal_query": q, "context": "", "label": label}

        tasks = [_retrieve_one(sq) for sq in sub_queries]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        sub_contexts = [r for r in results if isinstance(r, dict)]

        # Build merged context with per-violation separation
        merged_context = self._format_multi_violation_context(sub_contexts)

        logging.info(
            f"[STEP2] Parallel retrieval complete: "
            f"{len(sub_contexts)} sub-contexts, "
            f"merged context length={len(merged_context)}"
        )

        return {"context": merged_context, "sub_contexts": sub_contexts}

    @staticmethod
    def _format_multi_violation_context(sub_contexts: list[dict]) -> str:
        """
        Gộp N sub-contexts thành 1 context string có delimiter rõ ràng
        để Generator phân biệt dữ liệu từng vi phạm.
        """
        if not sub_contexts:
            return ""

        total = len(sub_contexts)
        SEP = "═" * 60

        parts = []
        for i, sc in enumerate(sub_contexts, 1):
            label = sc.get("label", f"Vi phạm {i}")
            ctx = sc.get("context", "")

            header = (
                f"\n{SEP}\n"
                f"  VI PHẠM {i}/{total}: {label}\n"
                f"{SEP}"
            )

            if ctx and "Không tìm thấy" not in ctx:
                parts.append(f"{header}\n{ctx}")
            else:
                parts.append(
                    f"{header}\n"
                    f"(Không tìm thấy thông tin cho vi phạm này trong đồ thị tri thức.)"
                )

        summary = (
            f"[MULTI-VIOLATION CONTEXT: {total} vi phạm riêng biệt]\n"
            f"Mỗi phần 'VI PHẠM X' chứa dữ liệu độc lập — "
            f"KHÔNG được ghép mức phạt từ vi phạm này sang vi phạm khác.\n"
        )

        return summary + "\n".join(parts)

    # ------------------------------------------------------------------
    # Step 3 — Reflector / Critic
    # ------------------------------------------------------------------

    # Từ khóa cho thấy context chứa thông tin xử phạt thực sự
    _PENALTY_KEYWORDS: tuple = (
        "phạt tiền", "triệu đồng", "nghìn đồng",
        "tước quyền sử dụng giấy phép", "tước bằng",
        "tạm giữ phương tiện", "tạm giữ xe",
        "trừ điểm", "điểm giấy phép lái xe",
        "cảnh cáo",
    )
    # Markers xuất hiện khi context thực sự đến từ graph retrieval
    _RETRIEVAL_MARKERS: tuple = (
        "--- nguồn", "[multi-violation context", "vi phạm 1/",
        "nghị định 168/2024/nđ-cp", "═══",
    )
    # Alias loại xe để cover các cách viết khác nhau trong context
    _VEHICLE_ALIASES: dict = {
        "xe máy": ["xe máy", "mô tô", "xe gắn máy", "moto"],
        "mô tô":  ["xe máy", "mô tô", "xe gắn máy", "moto"],
        "ô tô":   ["ô tô", "xe ô tô", "xe con", "xe tải", "ô tô con"],
        "xe tải": ["xe tải", "ô tô tải", "xe chở hàng"],
    }

    @classmethod
    def _is_high_confidence_context(cls, context: str, entities: dict) -> bool:
        """
        Pre-check trước khi gọi LLM reflector. Bypass khi đủ 3 điều kiện:
        1. Context có dữ liệu xử phạt (penalty keywords)
        2. Context đến từ graph retrieval (retrieval markers)
        3. Context liên quan đến đúng vi phạm và loại xe user hỏi
        """
        ctx_lower = context.lower()

        # Điều kiện 1: phải có từ khóa phạt
        if not any(kw in ctx_lower for kw in cls._PENALTY_KEYWORDS):
            return False

        # Điều kiện 2: phải có marker retrieval hợp lệ
        if not any(marker in ctx_lower for marker in cls._RETRIEVAL_MARKERS):
            return False

        # Điều kiện 3a: vi phạm phải xuất hiện trong context
        violation = entities.get("violation", "").lower()
        if violation:
            keywords = [w for w in violation.split() if len(w) > 3][:3]
            if keywords and not any(kw in ctx_lower for kw in keywords):
                logging.info(
                    f"[STEP3] Pre-check fail: violation keywords {keywords} "
                    f"không tìm thấy trong context → gọi LLM"
                )
                return False

        # Điều kiện 3b: vehicle_type phải khớp nếu user có chỉ định
        vehicle_type = entities.get("vehicle_type", "").lower()
        if vehicle_type:
            aliases = cls._VEHICLE_ALIASES.get(vehicle_type, [vehicle_type])
            if not any(alias in ctx_lower for alias in aliases):
                logging.info(
                    f"[STEP3] Pre-check fail: vehicle_type='{vehicle_type}' "
                    f"không tìm thấy trong context → gọi LLM"
                )
                return False

        return True

    async def _node_reflector(self, state: RAGState) -> dict:
        """
        Step 3: LLM đánh giá context — 3 verdict:
          sufficient          → đủ thông tin, đi đến generator
          needs_clarification → có data nhưng thiếu tham số, hỏi ngược user
          not_found           → không có trong NĐ 168, chuyển sang web search

        Bổ sung: trigger_search flag
          true  → Graph data không khớp hoặc độ tin cậy thấp → force web search
          false → context đáng tin cậy

        Complexity-aware:
          Level 1 (Simple) → skip hoàn toàn, trả "sufficient"
          Level 2 (Medium) → gọi _llm_ref_l2 (thinking_budget=512)
          Level 3 (Complex)→ gọi _llm_ref_l3 (thinking_budget=1024)
        """
        complexity_level = state.get("complexity_level", 2)

        # ── Level 1: Skip Reflector hoàn toàn ──────────────────────────────
        if complexity_level == 1:
            logging.info(
                "[STEP3] SKIP Reflector (complexity_level=1 — Simple query). "
                "Trả thẳng 'sufficient' để tiết kiệm latency."
            )
            return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}

        # ── Level 2/3: Chọn LLM theo level ─────────────────────────────────
        _llm_map = {
            2: self._llm_ref_l2,  # thinking_budget=512
            3: self._llm_ref_l3,  # thinking_budget=1024
        }
        llm_reflector = _llm_map.get(complexity_level, self._llm_ref_l2)

        messages = state.get("messages", [])
        question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                question = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        context = state.get("context", "")
        entities = state.get("entities", {})

        # Pre-check: bypass LLM khi context rõ ràng đủ mạnh và đúng context
        # (Đã tắt do Pre-check chỉ kiểm tra keyword, dễ bị lọt các "vùng xám" như xe tự lái.
        # Chi phí của Gemini 3 Flash rất rẻ, nên gọi LLM Reflector 100% để đảm bảo chất lượng)
        if context and self._is_high_confidence_context(context, entities):
            logging.info(
                f"[STEP3] Pre-check condition met (level={complexity_level}), nhưng đã vô hiệu hóa bypass. "
                "Vẫn gọi LLM Reflector để bắt các ca 'vùng xám' (Semantic Mismatch)."
            )
            # return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}

        prompt = self._reflector_prompt.format(
            question=question,
            context=context if context else "(Không tìm được dữ liệu từ đồ thị tri thức)",
            entities=json.dumps(entities, ensure_ascii=False, indent=2),
        )
        try:
            response = await llm_reflector.ainvoke([HumanMessage(content=prompt)])
            raw = _extract_ai_text(response).strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw.strip())
            data = json.loads(raw)
            verdict = data.get("verdict", "sufficient")
            clarification_q = data.get("clarification_question", "")
            trigger_search = data.get("trigger_search", False)

            logging.info(
                f"[STEP3] level={complexity_level}, verdict={verdict!r}, "
                f"trigger_search={trigger_search}"
            )
            return {
                "reflection": verdict,
                "clarification_question": clarification_q,
                "trigger_search": trigger_search,
            }
        except Exception as e:
            logging.error(f"[STEP3] Lỗi: {e} — fallback sufficient")
            return {"reflection": "sufficient", "clarification_question": "", "trigger_search": False}

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
            return {"context": "(Không xác định được câu hỏi để tìm kiếm web.)", "web_sources": []}

        web_tool = next((t for t in self._tools if t.name == "web_search"), None)
        if not web_tool:
            logging.warning("[STEP3c] web_search không khả dụng — thiếu SERPER_API_KEY.")
            return {"context": "(Web search không khả dụng.)", "web_sources": []}

        logging.info(f"[STEP3c] Tìm web cho: {question[:80]}")
        try:
            result, web_sources = await web_tool._execute_with_sources(query=question, num=5)
            logging.info(f"[STEP3c] Tìm được {len(web_sources)} nguồn web.")
            return {
                "context": (
                    "⚠️ Thông tin KHÔNG có trong Nghị định 168/2024/NĐ-CP. "
                    "Kết quả bổ sung từ tìm kiếm web:\n\n" + result
                ),
                "web_sources": web_sources,
            }
        except Exception as e:
            logging.error(f"[STEP3c] Lỗi web search: {e}")
            return {"context": f"Lỗi khi tìm kiếm web: {e}", "web_sources": []}

    # ------------------------------------------------------------------
    # Step 4 — Generator
    # ------------------------------------------------------------------

    async def _node_generator(self, state: RAGState) -> dict:
        """
        Step 4: Tổng hợp câu trả lời cuối cùng.
        Context (từ Neo4j hoặc web) được inject vào messages trước khi gọi LLM.

        response_style từ Router quyết định giọng văn:
          - "legal"   → format Terminal cứng, trích dẫn pháp lý nghiêm túc
          - "natural"  → trả lời như một người bạn thân thiện

        Complexity-aware (thinking_budget):
          - Level 1 (Simple):  thinking_budget=0  (tắt thinking)
          - Level 2 (Medium):  thinking_budget=2048
          - Level 3 (Complex): thinking_budget=4096
        """
        complexity_level = state.get("complexity_level", 2)
        _llm_gen_map = {
            1: self._llm_gen_l1,  # thinking_budget=0
            2: self._llm_gen_l2,  # thinking_budget=2048
            3: self._llm_gen_l3,  # thinking_budget=4096
        }
        llm = _llm_gen_map.get(complexity_level, self._llm_gen_l2)
        logging.info(
            f"[STEP4] LLM selected: gen_l{complexity_level}, "
            f"thinking_budget={({1: 0, 2: 2048, 3: 4096}).get(complexity_level, 2048)}"
        )

        messages = list(state.get("messages", []))
        context = state.get("context", "")
        style = state.get("response_style", "legal")

        # 1. Tách SystemMessage cũ ra khỏi tin nhắn User/AI để không bị cắt xoá
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        # 2. Giữ 8 tin nhắn lịch sử gần nhất (4 lượt chat)
        recent_chat_msgs = chat_msgs[-8:]

        # 3. Chọn system prompt theo response_style + độ phức tạp
        # level 1 + single violation => dùng prompt rút gọn để trả lời nhanh cho 1 hành vi
        is_single_violation = len(state.get("sub_queries", [])) == 0
        if style == "legal" and complexity_level == 1 and is_single_violation:
            chosen_prompt = self._system_prompt_compact
        elif style == "legal":
            chosen_prompt = self._system_prompt
        else:
            chosen_prompt = self._natural_prompt

        # 4. Ghép lại danh sách messages cho LLM
        messages_to_llm = system_msgs + recent_chat_msgs

        if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
            messages_to_llm = [SystemMessage(content=chosen_prompt)] + messages_to_llm

        if context:
            messages_to_llm = messages_to_llm + [
                SystemMessage(
                    content=(
                        "[RETRIEVED_CONTEXT]\n"
                        f"{context}\n"
                        "[/RETRIEVED_CONTEXT]\n\n"
                        "HƯỚNG DẪN SỬ DỤNG CONTEXT:\n"
                        "1. Mỗi block bắt đầu bằng '═══ [Điều X, Khoản Y...] ═══' là một anchor duy nhất.\n"
                        "   → Chỉ trích dẫn số Điều/Khoản nếu nó xuất hiện TƯỜNG MINH trong header '═══' đó.\n"
                        "2. TUYỆT ĐỐI KHÔNG ghép số Điều từ block này với mức phạt từ block khác.\n"
                        "3. TUYỆT ĐỐI KHÔNG dùng kiến thức ngoài context để suy ra số Điều/Khoản.\n"
                        "4. Nếu không tìm thấy header '═══' → không ghi Điều/Khoản, chỉ mô tả mức phạt.\n"
                        "5. Nếu context bắt đầu bằng '[MULTI-VIOLATION CONTEXT]': mỗi phần 'VI PHẠM X' "
                        "là nguồn dữ liệu riêng biệt. Xử lý từng phần và tổng hợp cộng dồn cuối cùng.\n"
                    )
                )
            ]

        # Inject skill 02 + 03 cho legal flow để bổ sung hướng dẫn đọc graph và kiểm toán trích dẫn
        if style == "legal":
            skill_parts = [
                s for s in [self._skill_graph_analyzer, self._skill_citation_validator]
                if s
            ]
            if skill_parts:
                messages_to_llm = messages_to_llm + [
                    SystemMessage(content="\n\n---\n\n".join(skill_parts))
                ]

        try:
            response = await llm.ainvoke(messages_to_llm)
            return {"messages": [response]}
        except Exception as e:
            logging.error(f"[STEP4] Lỗi: {e}")
            return {"messages": [AIMessage(content=f"Xin lỗi, đã xảy ra lỗi khi soạn câu trả lời: {e}")]}

    # ------------------------------------------------------------------
    # Direct Answer (câu hỏi không cần tra luật)
    # ------------------------------------------------------------------

    async def _node_agent_direct(self, state: RAGState) -> dict:
        """
        Trả lời trực tiếp cho câu hỏi direct_answer (chào hỏi, hỏi về chatbot, v.v.)
        Luôn dùng style "natural" — giọng văn thân thiện.
        """
        messages = list(state.get("messages", []))
        
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
        recent_chat_msgs = chat_msgs[-8:]

        messages_to_llm = system_msgs + recent_chat_msgs

        # Agent Direct luôn dùng natural prompt (thân thiện)
        if not any(isinstance(m, SystemMessage) for m in messages_to_llm):
            messages_to_llm = [SystemMessage(content=self._natural_prompt)] + messages_to_llm

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
    # Cache Check (sau router_rewrite, trước retriever)
    # ------------------------------------------------------------------

    async def _node_cache_check(self, state: RAGState, config: dict = None) -> dict:
        """
        Kiểm tra Semantic Cache sau khi router_rewrite đã bóc tách entities.

        Dùng legal_query (đã chuẩn hóa) làm input tìm kiếm cache.
        Nếu HIT → set cache_hit=True, cached_response=response text.
        Nếu MISS → set cache_hit=False, pipeline tiếp tục bình thường.

        Ưu tiên nguồn enable_cache:
          1. config["configurable"]["enable_cache"]  ← cao nhất (eval path)
          2. state["enable_cache"]                   ← từ router_rewrite node
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

    # ------------------------------------------------------------------
    # Generator Cached (trả lời từ cache, skip retriever/reflector)
    # ------------------------------------------------------------------

    async def _node_generator_cached(self, state: RAGState) -> dict:
        """Emit cached response trực tiếp, không cần gọi LLM."""
        cached_response = state.get("cached_response", "")
        return {"messages": [AIMessage(content=cached_response)]}


    @staticmethod
    def _route_after_router(state: RAGState) -> str:
        """Step 1 → cache_check (cho use_tool), direct answer, hoặc reject."""
        route = state.get("route")
        if route == "direct_answer":
            return "agent_direct"
        if route == "out_of_domain":
            return "agent_reject"
        return "cache_check"  # use_tool → kiểm tra cache trước

    @staticmethod
    def _route_after_cache(state: RAGState) -> str:
        """Cache check → generator_cached (nếu HIT) hoặc retriever (nếu MISS)."""
        if state.get("cache_hit", False):
            logging.info("[ROUTING] cache_hit=True → generator_cached (skip retriever/reflector)")
            return "generator_cached"
        return "retriever"

    @staticmethod
    def _route_after_reflector(state: RAGState) -> str:
        """
        Step 3 → routing:
          trigger_search = true   → web_search_fallback (ưu tiên cao nhất — force search)
          sufficient              → generator (Step 4)
          needs_clarification     → clarifier (hỏi ngược user, rồi END)
          not_found               → web_search_fallback → generator

        NOTE: LangGraph KHÔNG truyền `config` vào routing function của add_conditional_edges.
        enable_web_search được lưu vào state bởi _node_router_rewrite rồi đọc tại đây.
        """
        # Đọc từ state (không đọc từ config — routing fn không nhận được config)
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

        # ── Ưu tiên 1: Force search (threshold hoặc reflector detection) ─────
        if trigger_search:
            logging.info(
                "[ROUTING] trigger_search=True → chuyển sang web_search_fallback "
                "(Graph data không đủ tin cậy hoặc không khớp)"
            )
            return "web_search_fallback"

        # ── Ưu tiên 2: Verdict routing ──────────────────────────────────────
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
        Pipeline 5 bước (có Semantic Cache):

             [START]
                │
          [router_rewrite]          ← Step 1: Phân loại + Bóc tách entities + Sub-queries
                │
         ┌──────┴──────────────┬────────────────┐
         │                     │                │
   direct_answer?          use_tool?      out_of_domain?
         │                     │                │
   [agent_direct]        [cache_check]    [agent_reject]
         │                     │                │
        END           ┌───────┴───────┐        END
                      │               │
                   cache_hit?     cache_miss?
                      │               │
              [generator_cached]  [retriever]
                      │               │
                     END         [reflector]
                                      │
                     ┌────────────────┼────────────────┐
                     │                │                │
               sufficient?  needs_clarification?  not_found?
                     │                │                │
                [generator]      [clarifier]   [web_search_fallback]
                     │                │                │
                    END              END          [generator]
                                                       │
                                                      END

        Multi-violation: retriever node chạy song song qua asyncio.gather
        """
        graph = StateGraph(RAGState)

        # Nodes
        graph.add_node("router_rewrite",      self._node_router_rewrite)
        graph.add_node("cache_check",         self._node_cache_check)
        graph.add_node("generator_cached",    self._node_generator_cached)
        graph.add_node("agent_direct",        self._node_agent_direct)
        graph.add_node("agent_reject",        self._node_agent_reject)
        graph.add_node("retriever",           self._node_retriever)
        graph.add_node("reflector",           self._node_reflector)
        graph.add_node("clarifier",           self._node_clarifier)
        graph.add_node("web_search_fallback", self._node_web_search_fallback)
        graph.add_node("generator",           self._node_generator)

        # Edges
        graph.set_entry_point("router_rewrite")
        graph.add_conditional_edges(
            "router_rewrite",
            self._route_after_router,
            {
                "agent_direct": "agent_direct",
                "cache_check":  "cache_check",
                "agent_reject": "agent_reject",
            },
        )
        graph.add_edge("agent_direct", END)
        graph.add_edge("agent_reject", END)
        graph.add_conditional_edges(
            "cache_check",
            self._route_after_cache,
            {
                "generator_cached": "generator_cached",
                "retriever":        "retriever",
            },
        )
        graph.add_edge("generator_cached", END)
        graph.add_edge("retriever", "reflector")
        graph.add_conditional_edges(
            "reflector",
            self._route_after_reflector,
            {
                "generator":          "generator",
                "clarifier":          "clarifier",
                "web_search_fallback": "web_search_fallback",
            },
        )
        graph.add_edge("clarifier",           END)
        graph.add_edge("web_search_fallback", "generator")
        graph.add_edge("generator",           END)

        compiled = graph.compile(checkpointer=self._checkpointer)
        cache_status = "có cache" if self._cache and self._cache.is_connected else "không cache"
        if self._checkpointer:
            logging.info(f"✅ LangGraph compiled ({cache_status}) — Pipeline: Router→Cache→Retriever→Reflector→Generator.")
        else:
            logging.warning(f"⚠️  LangGraph compiled (stateless, {cache_status}) — Pipeline: Router→Cache→Retriever→Reflector→Generator.")
        return compiled

    # ------------------------------------------------------------------
    # Source extraction helpers
    # ------------------------------------------------------------------

    _RE_GRAPH_SOURCE = re.compile(
        r"---\s*Nguồn\s+(\S+)\s*\(score:\s*([\d.]+)\s*\|[^)]*\)\s*---"
    )
    _RE_WEB_URL = re.compile(r"^URL\s*:\s*(https?://\S+)", re.MULTILINE)
    # Nhận diện các chuỗi chứa "Điều", "Khoản", "Điểm" (có thể độc lập hoặc kết hợp)
    # Bắt được: "Điều 18", "Khoản 8", "Điểm a", "Điểm a Khoản 8 Điều 18", "Khoản 5 Điều 26", v.v.
    _RE_DIEU_KHOAN = re.compile(
        r"(?:Điểm\s+[a-zđ0-9]+\s+)?(?:Khoản\s+\d+\s+)?(?:Điều\s+\d+)|(?:Khoản\s+\d+)|(?:Điểm\s+[a-zđ0-9]+(?:\s+Khoản\s+\d+)?)",
        re.IGNORECASE,
    )
    # Parse entity IDs dạng: d18_k8_a → "Điều 18 Khoản 8 Điểm a"
    _RE_ENTITY_ID = re.compile(
        r"\b(d(\d+)(?:_k(\d+))?(?:_([a-zđ]+))?)\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _parse_legal_anchors(context: str) -> list[str]:
        """
        Parse nhanh các anchor pháp lý (Điều/Khoản/Điểm) từ context trả về bởi retriever.
        Lọc bỏ các block có score thấp so với top score để tránh nhiễu.
        Dedup + giữ thứ tự xuất hiện, tối đa 8 anchors để tránh quá dài.

        Parse từ 2 nguồn:
        1. Entity IDs dạng: d18_k8_a → "Điều 18 Khoản 8 Điểm a"
        2. Text anchors dạng: "Điều 18", "Khoản 8", "Điểm a Khoản 8", v.v.
        """
        if not context or "Không tìm thấy" in context:
            return []

        # Tách context thành các block bằng header chứa score
        headers = list(RAGService._RE_GRAPH_SOURCE.finditer(context))
        valid_context_text = context

        if headers:
            try:
                max_score = float(headers[0].group(2))
            except ValueError:
                max_score = 0.0

            threshold = max_score * 0.5  # Giảm từ 0.75 → 0.5 để bắt được nhiều anchors hơn
            kept_blocks = []

            for i, match in enumerate(headers):
                try:
                    score = float(match.group(2))
                except ValueError:
                    score = 0.0

                if score >= threshold:
                    start_idx = match.end()
                    end_idx = headers[i+1].start() if i+1 < len(headers) else len(context)
                    kept_blocks.append(context[start_idx:end_idx])

            if kept_blocks:
                valid_context_text = "\n".join(kept_blocks)

        seen: set[str] = set()
        anchors: list[str] = []

        def capitalize_kw(match_obj):
            return match_obj.group(0).capitalize()

        # 1. Parse entity IDs (d18_k8_a → "Điều 18 Khoản 8 Điểm a")
        for m in RAGService._RE_ENTITY_ID.finditer(valid_context_text):
            full_id, dieu_num, khoan_num, diem_letter = m.groups()
            parts = []
            if dieu_num:
                parts.append(f"Điều {dieu_num}")
            if khoan_num:
                parts.append(f"Khoản {khoan_num}")
            if diem_letter:
                parts.append(f"Điểm {diem_letter}")

            if parts:
                anchor = " ".join(parts)
                key = anchor.lower()
                if key not in seen:
                    seen.add(key)
                    anchors.append(anchor)

        # 2. Parse text anchors (Điều X, Khoản Y, Điểm Z, v.v.)
        for m in RAGService._RE_DIEU_KHOAN.finditer(valid_context_text):
            token = m.group(0).strip()
            # Clean up token (e.g "điểm a khoản 1 điều 32" → "Điểm a Khoản 1 Điều 32")
            token_clean = re.sub(r'(điểm|khoản|điều|mục)', capitalize_kw, token, flags=re.IGNORECASE)

            key = token_clean.lower()
            if key not in seen and "Điều này" not in token_clean:  # Loại bỏ "Điều này"
                seen.add(key)
                anchors.append(token_clean)

        return anchors[:8]  # giới hạn 8 anchors

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

    @staticmethod
    def _calculate_cost(input_tokens: int, output_tokens: int, thinking_tokens: int) -> float:
        """
        Calculate estimated cost based on Gemini Flash pricing.

        Gemini Flash Preview pricing (as of 2026):
        - Input: $0.075 per 1M tokens
        - Output: $0.30 per 1M tokens
        - Thinking: $0.30 per 1M tokens (same as output)

        Returns cost in USD.
        """
        input_cost = (input_tokens / 1_000_000) * 0.075
        output_cost = (output_tokens / 1_000_000) * 0.30
        thinking_cost = (thinking_tokens / 1_000_000) * 0.30

        total_cost = input_cost + output_cost + thinking_cost
        return round(total_cost, 6)  # Round to 6 decimal places

    # ------------------------------------------------------------------
    # Pipeline streaming (LangGraph astream_events v2)
    # ------------------------------------------------------------------

    async def ask_stream(
        self,
        question: str,
        conversation_id: str | None = None,
        enable_web_search: bool = True,
        enable_cache: bool = True,
    ):
        import time

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
        final_answer_text = ""  # Thu thập response text để store vào cache
        final_route = ""  # Route từ router_rewrite
        final_entities = {}  # Entities từ router_rewrite
        final_legal_query = ""  # Legal query từ router_rewrite
        final_verdict = ""  # Reflector verdict (để gate cache store)
        final_context = ""  # Context cuối cùng từ retriever/web_search để trả metadata

        # Buffer để parse thẻ <thinking> từ chuỗi văn bản của Kimi
        tag_buffer = ""
        is_thinking = False
        tag_start = "<thinking>"
        tag_end = "</thinking>"

        # ── Metrics Tracking ──────────────────────────────────────────────
        start_time = time.time()
        ttft = None  # Time to first token
        first_token_received = False

        # Token tracking
        total_input_tokens = 0
        total_output_tokens = 0
        total_thinking_tokens = 0

        # Node timing tracking
        node_timings = {}  # {node_name: {"start": time, "duration": ms}}
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
                    # Track node start time
                    current_node = evt_name
                    current_node_start = time.time()

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
                    elif evt_name == "cache_check":
                        yield json.dumps({"type": "process", "content": "⚡ Kiểm tra bộ nhớ đệm ngữ nghĩa..."}, ensure_ascii=False) + "\n"
                    elif evt_name == "generator_cached":
                        yield json.dumps({"type": "process", "content": "⚡ Phản hồi từ bộ nhớ đệm..."}, ensure_ascii=False) + "\n"

                # ── LLM streaming: chỉ từ generator & agent_direct ──────────
                if evt_type == "on_chat_model_stream" and evt_meta_node in _STREAM_NODES:
                    chunk = event["data"]["chunk"]

                    # Capture TTFT (time to first token)
                    if not first_token_received:
                        ttft = int((time.time() - start_time) * 1000)  # milliseconds
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

                # ── Capture token usage from on_chat_model_end ──────────────
                elif evt_type == "on_chat_model_end" and evt_meta_node in _STREAM_NODES:
                    # This is where Gemini sends the final usage_metadata
                    output_data = event.get("data", {}).get("output", {})

                    # Output could be AIMessage object or dict
                    usage_metadata = None
                    if hasattr(output_data, "usage_metadata"):
                        usage_metadata = output_data.usage_metadata
                    elif isinstance(output_data, dict):
                        usage_metadata = output_data.get("usage_metadata")

                    if usage_metadata:
                        logging.info(f"[METRICS] on_chat_model_end usage_metadata found: {usage_metadata}")

                        # usage_metadata is a dict, use .get() instead of getattr()
                        if isinstance(usage_metadata, dict):
                            total_input_tokens = usage_metadata.get("input_tokens", 0) or 0
                            total_output_tokens = usage_metadata.get("output_tokens", 0) or 0
                            # Thinking tokens are in output_token_details.reasoning for Gemini
                            output_details = usage_metadata.get("output_token_details", {})
                            total_thinking_tokens = output_details.get("reasoning", 0) or 0
                        else:
                            # Fallback for object-like usage_metadata
                            total_input_tokens = getattr(usage_metadata, "input_tokens", 0) or 0
                            total_output_tokens = getattr(usage_metadata, "output_tokens", 0) or 0
                            total_thinking_tokens = getattr(usage_metadata, "thinking_tokens", 0) or 0

                        logging.info(f"[METRICS] Captured tokens - input: {total_input_tokens}, output: {total_output_tokens}, thinking: {total_thinking_tokens}")
                    else:
                        logging.debug(f"[METRICS] on_chat_model_end but no usage_metadata. output type: {type(output_data)}")

                elif evt_type == "on_chain_end" and evt_name == evt_meta_node:
                    # Track node end time
                    if current_node == evt_name and current_node_start:
                        duration_ms = int((time.time() - current_node_start) * 1000)
                        node_timings[evt_name] = duration_ms
                        logging.info(f"[METRICS] Node {evt_name}: {duration_ms}ms")

                        # Track tool calls
                        if evt_name == "retriever":
                            tool_calls_count += 1
                            tool_call_details.append({
                                "tool": "graph_retrieval",
                                "duration_ms": duration_ms
                            })
                        elif evt_name == "web_search_fallback":
                            tool_calls_count += 1
                            tool_call_details.append({
                                "tool": "web_search",
                                "duration_ms": duration_ms
                            })

                    output = event.get("data", {}).get("output", {})

                    # ── Emit nội dung trực tiếp cho các node KHÔNG stream: clarifier, agent_reject ────────
                    # generator và agent_direct đã được stream qua on_chat_model_stream, không emit lại ở đây
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
                                collected_sources.extend(RAGService._extract_graph_sources(ctx))
                                # ── Yield legal anchor process event ─────────
                                anchors = RAGService._parse_legal_anchors(ctx)
                                if anchors:
                                    # Lấy tối đa 3 anchors đầu tiên để hiển thị thành 2-3 dòng process (mỗi điều là 1 process)
                                    for anchor in anchors[:3]:
                                        yield json.dumps(
                                            {"type": "process", "content": f"📖 Đang tham khảo: {anchor}"},
                                            ensure_ascii=False,
                                        ) + "\n"
                            elif evt_name == "web_search_fallback":
                                # Lấy danh sách web sources có cấu trúc từ state
                                ws = output.get("web_sources", [])
                                if ws:
                                    collected_sources.extend(
                                        {"type": "web", "url": s["url"], "title": s.get("title", "")}
                                        for s in ws
                                    )
                                else:
                                    # Fallback: regex nếu web_sources rỗng
                                    collected_sources.extend(RAGService._extract_web_sources(ctx))

                    # ── Cache: capture answer text from generator for store ──
                    if evt_name == "generator" and isinstance(output, dict):
                        for m in (output.get("messages", []) if isinstance(output, dict) else []):
                            if isinstance(m, AIMessage):
                                text = _extract_ai_text(m)
                                if text:
                                    final_answer_text = text

                    # ── Cache: track route/entities from router_rewrite ──────
                    if isinstance(output, dict):
                        if evt_name == "router_rewrite":
                            final_route = output.get("route", "")
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

        # Calculate cost (Gemini Flash pricing as of 2026)
        cost = self._calculate_cost(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            thinking_tokens=total_thinking_tokens
        )

        # Prepare metrics payload
        metrics = {
            "model": "gemini-3-flash-preview",  # Main model used
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
            "errorType": error_type
        }

        # Breakdown chi tiết để xác định bottleneck theo node.
        node_breakdown = {
            "routerRewriteTime": node_timings.get("router_rewrite"),
            "cacheCheckTime": node_timings.get("cache_check"),
            "retrievalTime": node_timings.get("retriever"),
            "reflectorTime": node_timings.get("reflector"),
            "generatorTime": node_timings.get("generator"),
            "generatorCachedTime": node_timings.get("generator_cached"),
            "clarifierTime": node_timings.get("clarifier"),
            "webSearchTime": node_timings.get("web_search_fallback"),
        }

        executed_breakdown = {
            k: v for k, v in node_breakdown.items()
            if isinstance(v, int)
        }
        slowest_node = None
        if executed_breakdown:
            slowest_name = max(executed_breakdown, key=executed_breakdown.get)
            slowest_node = {
                "node": slowest_name,
                "durationMs": executed_breakdown[slowest_name],
            }

        metrics["nodeTimings"] = node_breakdown
        metrics["slowestNode"] = slowest_node

        logging.info(f"[METRICS] Final metrics: {metrics}")
        logging.info(f"[METRICS] Node breakdown: {node_breakdown}")
        if slowest_node:
            logging.info(
                f"[METRICS] Slowest node: {slowest_node['node']}="
                f"{slowest_node['durationMs']}ms"
            )

        # Send metrics before metadata and done
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
            and final_verdict == "sufficient"  # chỉ cache response đã qua reflector và được approved
            and final_answer_text
            and final_legal_query
            and not error_message
        ):
            import asyncio

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
                score_threshold=0.010,  # Ngưỡng thấp nhất để chấp nhận kết quả (thấp hơn → force web search)
                # Timeouts for parallel branches
                keyword_timeout=3.0,
                vector_timeout=5.0,
                graph_timeout=5.0,
                consequence_timeout=3.0,  # New: consequence-first branch
                # RRF threshold
                rrf_threshold=0.016,  # Balanced mode
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

    async def close(self):
        if self._cache:
            await self._cache.close()
        if self._driver:
            await self._driver.close()
            logging.info("Đã đóng kết nối Neo4j.")
