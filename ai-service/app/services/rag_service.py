import asyncio
import logging
from pathlib import Path

import neo4j
import yaml
from fastapi import HTTPException
from neo4j import AsyncGraphDatabase, exceptions
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.core.state import RAGState

# ---------------------------------------------------------------------------
# Helpers: load YAML prompts
# ---------------------------------------------------------------------------
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Đọc trường `template` từ file YAML trong thư mục prompts/."""
    path = _PROMPTS_DIR / filename
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["template"]


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------

class RAGService:
    def __init__(self):
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        self._api_key = settings.GOOGLE_API_KEY
        self._embed_model_id = settings.EMBED_MODEL_ID

        self._driver = None
        self._llm = None
        self._embed_model = None

        # Nạp prompt từ YAML một lần khi khởi tạo service
        self._prompt_rewrite: str = _load_prompt("rewrite_legal_query.yaml")
        self._prompt_synthesis: str = _load_prompt("synthesis.yaml")

    async def initialize(self):
        """Khởi tạo tất cả kết nối và load model — gọi 1 lần trong lifespan startup."""
        loop = asyncio.get_running_loop()
        await self._connect_neo4j()
        self._connect_llm()
        await loop.run_in_executor(None, self._load_embed_model)

    # ------------------------------------------------------------------
    # Kết nối
    # ------------------------------------------------------------------

    async def _connect_neo4j(self):
        try:
            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
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
            genai.configure(api_key=self._api_key)
            self._llm = genai.GenerativeModel("gemini-2.5-flash")
            logging.info("✅ Kết nối Gemini API thành công!")
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
    # Bước 0: Query Transformation
    # ------------------------------------------------------------------

    async def rewrite_legal_query(self, user_query: str) -> str:
        """Chuyển câu hỏi dân dã sang thuật ngữ pháp lý."""
        if not self._llm:
            raise HTTPException(status_code=503, detail="Dịch vụ LLM không khả dụng.")

        prompt = self._prompt_rewrite.format(user_query=user_query)
        try:
            response = await self._llm.generate_content_async(prompt)
            rewritten = response.text.strip()
            logging.info(f"[QUERY REWRITE] '{user_query}' -> '{rewritten}'")
            return rewritten
        except Exception as e:
            logging.warning(f"[QUERY REWRITE] Lỗi rewrite, dùng câu gốc: {e}")
            return user_query

    # ------------------------------------------------------------------
    # Bước 1: Tạo embedding
    # ------------------------------------------------------------------

    def get_embedding(self, text: str) -> list:
        if not self._embed_model:
            raise HTTPException(status_code=503, detail="Embedding model không khả dụng.")
        return self._embed_model.encode(text).tolist()

    # ------------------------------------------------------------------
    # Bước 2: Vector Search + 2-hop Traversal
    # ------------------------------------------------------------------

    async def hybrid_query(self, legal_query: str) -> tuple[list, str]:
        """Truy vấn Neo4j bằng vector search + graph traversal."""
        if not self._driver:
            raise HTTPException(status_code=503, detail="Không thể kết nối Neo4j.")

        loop = asyncio.get_running_loop()
        question_vector = await loop.run_in_executor(None, self.get_embedding, legal_query)

        cypher_query = """
        CALL db.index.vector.queryNodes('legal_vector_index', 5, $vector)
        YIELD node, score
        OPTIONAL MATCH (node)-[*1..2]-(related:Entity)
        WHERE related.label IN ['Article', 'Action', 'Consequence', 'Subject']
        RETURN
            node.id         AS id,
            node.text       AS text,
            node.raw_text   AS raw_content,
            collect(DISTINCT related.raw_text) AS context_list,
            score
        ORDER BY score DESC
        """

        try:
            async with self._driver.session(
                database="neo4j",
                default_access_mode=neo4j.WRITE_ACCESS,
            ) as session:
                result = await session.run(cypher_query, vector=question_vector)
                records = await result.data()

                logging.info(f"[NEO4J SEARCH] Số node tìm được: {len(records)}")
                for i, r in enumerate(records):
                    logging.info(
                        f"  #{i+1} id={r['id']} score={r['score']:.4f} text={r['text']}"
                    )

                context_blocks = []
                for r in records:
                    block = f"--- Nguồn {r['id']} ---\n{r['raw_content']}\n"
                    block += "\n".join([str(c) for c in r["context_list"] if c])
                    context_blocks.append(block)

                return records, "\n\n".join(context_blocks)
        except Exception as e:
            logging.error(f"[NEO4J SEARCH] Lỗi truy vấn: {e}")
            raise HTTPException(status_code=500, detail=f"Lỗi truy vấn Neo4j: {e}")

    # ------------------------------------------------------------------
    # Bước 3: Tổng hợp câu trả lời
    # ------------------------------------------------------------------

    def _build_synthesis_prompt(self, question: str, context: str) -> str:
        return self._prompt_synthesis.format(context=context, question=question)

    async def synthesize_answer(self, question: str, context: str) -> str:
        if not self._llm:
            raise HTTPException(status_code=503, detail="Dịch vụ LLM không khả dụng.")
        full_prompt = self._build_synthesis_prompt(question, context)
        try:
            response = await self._llm.generate_content_async(full_prompt)
            return response.text
        except Exception as e:
            logging.error(f"[SYNTHESIZE] Lỗi tổng hợp câu trả lời: {e}")
            raise HTTPException(status_code=500, detail="Lỗi khi tổng hợp câu trả lời.")

    async def synthesize_answer_stream(self, question: str, context: str):
        """Async generator yield từng text chunk từ Gemini streaming API."""
        if not self._llm:
            raise HTTPException(status_code=503, detail="Dịch vụ LLM không khả dụng.")
        full_prompt = self._build_synthesis_prompt(question, context)
        try:
            response = await self._llm.generate_content_async(full_prompt, stream=True)
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logging.error(f"[SYNTHESIZE STREAM] Lỗi: {e}")
            raise

    # ------------------------------------------------------------------
    # Pipeline chính (non-streaming)
    # ------------------------------------------------------------------

    async def ask(self, question: str) -> dict:
        legal_query = await self.rewrite_legal_query(question)
        records, context = await self.hybrid_query(legal_query)

        if not records:
            return {
                "rewritten_query": legal_query,
                "records_found": 0,
                "answer": (
                    "Xin lỗi, tôi không tìm thấy thông tin liên quan trong cơ sở dữ liệu. "
                    "Bạn có thể thử hỏi câu khác."
                ),
            }

        answer = await self.synthesize_answer(question, context)
        return {
            "rewritten_query": legal_query,
            "records_found": len(records),
            "answer": answer,
        }

    # ------------------------------------------------------------------
    # LangGraph nodes
    # ------------------------------------------------------------------

    async def _node_rewrite(self, state: RAGState) -> RAGState:
        q: asyncio.Queue = state["queue"]
        await q.put({"type": "thought", "content": "🔍 Đang phân tích và chuẩn hóa câu hỏi..."})
        legal_query = await self.rewrite_legal_query(state["question"])
        await q.put({"type": "thought", "content": f"✅ Câu hỏi đã được chuẩn hóa: {legal_query}"})
        return {**state, "legal_query": legal_query}

    async def _node_search(self, state: RAGState) -> RAGState:
        q: asyncio.Queue = state["queue"]
        await q.put({"type": "thought", "content": "🗂️ Đang tra cứu cơ sở dữ liệu đồ thị..."})
        records, context = await self.hybrid_query(state["legal_query"])
        if records:
            sources_list = [r["id"] for r in records]
            sources_str = ", ".join(sources_list)
            await q.put(
                {"type": "thought", "content": f"✅ Tìm thấy {len(records)} đoạn luật liên quan: {sources_str}"}
            )
        else:
            await q.put(
                {"type": "thought", "content": "⚠️ Không tìm thấy dữ liệu phù hợp trong cơ sở dữ liệu."}
            )
        return {**state, "records": records, "context": context}

    async def _node_synthesize(self, state: RAGState) -> RAGState:
        q: asyncio.Queue = state["queue"]
        if not state["records"]:
            await q.put(
                {
                    "type": "answer",
                    "content": (
                        "Xin lỗi, tôi không tìm thấy thông tin liên quan trong cơ sở dữ liệu. "
                        "Bạn có thể thử hỏi câu khác."
                    ),
                }
            )
            await q.put({
                "type": "metadata",
                "content": {
                    "sources": [],
                    "reasoning_steps": 0
                }
            })
            return state
        await q.put({"type": "thought", "content": "🤔 Đang phân tích dữ liệu pháp lý và soạn thảo câu trả lời..."})
        async for chunk_text in self.synthesize_answer_stream(state["question"], state["context"]):
            await q.put({"type": "answer", "content": chunk_text})

        sources_list = [r["id"] for r in state["records"]]
        await q.put({
            "type": "metadata",
            "content": {
                "sources": sources_list,
                "reasoning_steps": 4
            }
        })
        return state

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(RAGState)
        graph.add_node("rewrite",    self._node_rewrite)
        graph.add_node("search",     self._node_search)
        graph.add_node("synthesize", self._node_synthesize)
        graph.set_entry_point("rewrite")
        graph.add_edge("rewrite",    "search")
        graph.add_edge("search",     "synthesize")
        graph.add_edge("synthesize", END)
        return graph.compile()

    # ------------------------------------------------------------------
    # Pipeline streaming (LangGraph)
    # ------------------------------------------------------------------

    async def ask_stream(self, question: str, conversation_id: str | None = None):
        """
        Async generator yield labeled NDJSON chunks:
          {"type": "thought", "content": "..."}
          {"type": "answer",  "content": "..."}
          {"type": "done"}
        """
        import json

        queue: asyncio.Queue = asyncio.Queue()
        initial_state: RAGState = {
            "question":    question,
            "legal_query": "",
            "records":     [],
            "context":     "",
            "queue":       queue,
        }
        graph = self._build_graph()

        async def run_graph():
            try:
                async for _ in graph.astream(initial_state):
                    pass
            except Exception as e:
                logging.error(f"[LANGGRAPH] Lỗi: {e}")
                await queue.put({"type": "thought", "content": f"❌ Lỗi trong quá trình xử lý: {e}"})
            finally:
                await queue.put(None)  # sentinel

        asyncio.create_task(run_graph())

        while True:
            item = await queue.get()
            if item is None:
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        if self._driver:
            await self._driver.close()
            logging.info("Đã đóng kết nối Neo4j.")
