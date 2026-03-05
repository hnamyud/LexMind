"""
app/tools/graph_retrieval.py
────────────────────────────
Đóng gói chức năng truy xuất đồ thị tri thức (Neo4j) thành LangChain Tool chuẩn.

Tại sao đóng gói thành Tool?
─────────────────────────────
- LangChain Tool là interface chuẩn cho agentic flow:
    * LangGraph ReAct agent có thể bind và gọi tool tự động.
    * Agent tự quyết "có cần tra cứu luật không" thay vì luôn luôn tra cứu.
    * Dễ compose với các tool khác (web search, calculator, v.v.).

Cách dùng trong agentic flow:
─────────────────────────────
    from app.tools.graph_retrieval import make_graph_retrieval_tool

    tool = make_graph_retrieval_tool(driver=driver, embed_model=embed_model)
    agent = create_react_agent(llm, tools=[tool], checkpointer=checkpointer)

Schema của tool (input):
    query: str  ← câu hỏi/thuật ngữ pháp lý cần tra cứu

Output trả về (str):
    Context text đã format, sẵn sàng đưa vào LLM prompt.
    Nếu không tìm thấy → trả về chuỗi thông báo rõ để LLM hiểu.
"""

import asyncio
import logging
from typing import Optional, Any

import neo4j
from langchain_core.tools import tool, BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class GraphRetrievalInput(BaseModel):
    """Schema đầu vào cho GraphRetrievalTool."""
    query: str = Field(
        description=(
            "Câu hỏi hoặc thuật ngữ pháp lý cần tra cứu trong cơ sở dữ liệu đồ thị. "
            "Nên dùng thuật ngữ chính xác (ví dụ: 'vượt đèn đỏ', 'nồng độ cồn vượt mức'). "
            "Tool sẽ tìm các điều khoản luật liên quan nhất."
        )
    )


# ---------------------------------------------------------------------------
# Tool class (hỗ trợ cả sync và async)
# ---------------------------------------------------------------------------

class GraphRetrievalTool(BaseTool):
    """
    LangChain Tool tra cứu đồ thị tri thức pháp lý.

    Thực hiện:
      1. Tạo vector embedding từ query.
      2. Vector search trên Neo4j (top-5 node gần nhất).
      3. 2-hop graph traversal để lấy entity liên quan.
      4. Trả về context text đã format cho LLM.

    Attributes
    ----------
    driver : neo4j.AsyncDriver
        Driver Neo4j async đã được khởi tạo sẵn.
    embed_model : SentenceTransformer
        Model embedding đã được load sẵn.
    top_k : int
        Số node tìm kiếm tối đa (mặc định: 5).
    """

    # ── Metadata bắt buộc của LangChain Tool ──────────────────────────────
    name: str = "search_legal_graph"
    description: str = (
        "Tra cứu cơ sở dữ liệu đồ thị tri thức pháp lý Việt Nam (Nghị định 168/2024/NĐ-CP). "
        "Dùng khi cần tìm thông tin về: mức phạt vi phạm giao thông, điều kiện tước giấy phép, "
        "quy định về nồng độ cồn, tốc độ, tải trọng, v.v. "
        "Input: câu hỏi hoặc từ khóa pháp lý. "
        "Output: các đoạn luật liên quan nhất."
    )
    args_schema: type[BaseModel] = GraphRetrievalInput
    return_direct: bool = False  # False = agent tiếp tục xử lý output

    # ── Dependency injection (không phải LangChain field chuẩn) ───────────
    # Dùng model_config để cho phép arbitrary type
    model_config = {"arbitrary_types_allowed": True}

    driver: Any = Field(default=None, exclude=True)
    embed_model: Any = Field(default=None, exclude=True)
    top_k: int = Field(default=5)

    # ── Cypher query ───────────────────────────────────────────────────────
    _CYPHER = """
    CALL db.index.vector.queryNodes('legal_vector_index', $top_k, $vector)
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

    # ------------------------------------------------------------------
    # Core logic (private)
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list:
        """Tạo vector embedding (CPU-bound, chạy trong executor)."""
        return self.embed_model.encode(text).tolist()

    async def _query_neo4j(self, vector: list) -> tuple[list, str]:
        """Truy vấn Neo4j async và format kết quả thành context string."""
        async with self.driver.session(
            database="neo4j",
            default_access_mode=neo4j.READ_ACCESS,  # chỉ đọc → dùng READ_ACCESS
        ) as session:
            result = await session.run(self._CYPHER, vector=vector, top_k=self.top_k)
            records = await result.data()

        logging.info(f"[GraphRetrievalTool] Tìm được {len(records)} node.")

        if not records:
            return [], ""

        context_blocks = []
        for r in records:
            block = f"--- Nguồn {r['id']} (độ tương đồng: {r['score']:.3f}) ---\n"
            block += f"{r['raw_content']}\n"
            related = [str(c) for c in r["context_list"] if c]
            if related:
                block += "\n".join(related)
            context_blocks.append(block)

        return records, "\n\n".join(context_blocks)

    # ------------------------------------------------------------------
    # LangChain interface — sync (bắt buộc override)
    # ------------------------------------------------------------------

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Sync fallback — chạy async trong event loop mới nếu không có sẵn."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Đang trong async context → chạy coroutine trực tiếp
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._arun(query))
                    return future.result()
            else:
                return loop.run_until_complete(self._arun(query))
        except Exception as e:
            logging.error(f"[GraphRetrievalTool] Lỗi sync: {e}")
            return f"Lỗi khi tra cứu: {e}"

    # ------------------------------------------------------------------
    # LangChain interface — async (ưu tiên dùng)
    # ------------------------------------------------------------------

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """
        Async entry point — được LangGraph agent gọi khi execute tool.

        Returns
        -------
        str
            Context text chứa các điều khoản luật liên quan,
            hoặc thông báo không tìm thấy để agent xử lý tiếp.
        """
        if not self.driver:
            return "Lỗi: Chưa kết nối cơ sở dữ liệu đồ thị."
        if not self.embed_model:
            return "Lỗi: Chưa tải embedding model."

        try:
            # Bước 1: Tạo embedding (CPU-bound → chạy trong executor)
            loop = asyncio.get_running_loop()
            vector = await loop.run_in_executor(None, self._embed, query)

            # Bước 2: Truy vấn Neo4j async
            records, context = await self._query_neo4j(vector)

            if not records:
                return (
                    "Không tìm thấy thông tin liên quan trong cơ sở dữ liệu đồ thị. "
                    "Câu hỏi có thể nằm ngoài phạm vi Nghị định 168/2024/NĐ-CP."
                )

            return context

        except Exception as e:
            logging.error(f"[GraphRetrievalTool] Lỗi: {e}")
            return f"Lỗi khi truy xuất đồ thị: {e}"


# ---------------------------------------------------------------------------
# Factory function — cách khởi tạo được khuyến nghị
# ---------------------------------------------------------------------------

def make_graph_retrieval_tool(
    driver: Any,
    embed_model: Any,
    top_k: int = 5,
) -> GraphRetrievalTool:
    """
    Tạo và trả về instance của GraphRetrievalTool.

    Parameters
    ----------
    driver : neo4j.AsyncDriver
        Driver sau khi đã gọi verify_connectivity().
    embed_model : SentenceTransformer
        Model embedding đã được load.
    top_k : int
        Số lượng node tìm kiếm tối đa.

    Returns
    -------
    GraphRetrievalTool
        Tool sẵn sàng bind vào LangChain agent.

    Example
    -------
    >>> tool = make_graph_retrieval_tool(driver, embed_model, top_k=5)
    >>> agent = create_react_agent(llm, tools=[tool], checkpointer=checkpointer)
    """
    return GraphRetrievalTool(driver=driver, embed_model=embed_model, top_k=top_k)
