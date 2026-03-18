"""
app/tools/graph_retrieval.py
────────────────────────────
Đóng gói chức năng truy xuất đồ thị tri thức (Neo4j) thành LangChain Tool chuẩn.

Chiến lược retrieval 3-prong SONG SONG:
─────────────────────────────────────────
  1. Keyword search  — tìm chính xác theo từ khóa (CONTAINS trên name/text)
  2. Vector search   — tìm theo ngữ nghĩa tương đồng (embedding cosine)
  3. Graph traversal — duyệt đồ thị dựa trên entities đã bóc tách từ router

Ba nhánh chạy đồng thời qua asyncio.gather, sau đó merge + deduplicate + rank.

Cách dùng trong agentic flow:
─────────────────────────────
    from app.tools.graph_retrieval import make_graph_retrieval_tool

    tool = make_graph_retrieval_tool(driver=driver, embed_model=embed_model)
    agent = create_react_agent(llm, tools=[tool], checkpointer=checkpointer)

Schema của tool (input):
    query    : str  ← câu hỏi/thuật ngữ pháp lý cần tra cứu
    entities : dict ← entities đã bóc tách từ router {violation, vehicle_type, subject, conditions}

Output trả về (str):
    Context text đã format, sẵn sàng đưa vào LLM prompt.
    Nếu không tìm thấy → trả về chuỗi thông báo rõ để LLM hiểu.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
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
    entities: dict = Field(
        default={},
        description=(
            "Entities đã bóc tách từ router: "
            "{violation, vehicle_type, subject, conditions[]}. "
            "Dùng cho graph traversal."
        )
    )


# ---------------------------------------------------------------------------
# Tool class (hỗ trợ cả sync và async)
# ---------------------------------------------------------------------------

class GraphRetrievalTool(BaseTool):
    """
    LangChain Tool tra cứu đồ thị tri thức pháp lý.

    Thực hiện SONG SONG 3 chiến lược:
      1. Keyword search  — CONTAINS trên name/text → exact match
      2. Vector search   — embedding cosine similarity → semantic match
      3. Graph traversal — entity-driven duyệt đồ thị → structural match

    Kết quả 3 nhánh được merge, deduplicate theo node.id, rank theo tổng hợp score.

    Attributes
    ----------
    driver : neo4j.AsyncDriver
        Driver Neo4j async đã được khởi tạo sẵn.
    embed_model : SentenceTransformer
        Model embedding đã được load sẵn.
    top_k : int
        Số node tìm kiếm tối đa mỗi nhánh (mặc định: 5).
    """

    # ── Metadata bắt buộc của LangChain Tool ──────────────────────────────
    name: str = "search_legal_graph"
    description: str = (
        "CÔNG CỤ ƯU TIÊN SỐ 1. LUÔN SỬ DỤNG CÔNG CỤ NÀY ĐẦU TIÊN để tra cứu "
        "cơ sở dữ liệu đồ thị tri thức pháp lý Việt Nam (Đặc biệt: Nghị định 168/2024/NĐ-CP). "
        "Dùng để tìm kiếm toàn bộ thông tin chuẩn xác về: mức phạt vi phạm giao thông, "
        "điều kiện tước giấy phép, quy định về nồng độ cồn, tốc độ, tải trọng, v.v. "
        "Input: câu hỏi hoặc cụm từ khóa pháp lý cốt lõi. "
        "Output: các đoạn luật liên quan trực tiếp sẵn sàng để trích dẫn."
    )
    args_schema: type[BaseModel] = GraphRetrievalInput
    return_direct: bool = False  # False = agent tiếp tục xử lý output

    # ── Dependency injection (không phải LangChain field chuẩn) ───────────
    # Dùng model_config để cho phép arbitrary type
    model_config = {"arbitrary_types_allowed": True}

    driver: Any = Field(default=None, exclude=True)
    embed_model: Any = Field(default=None, exclude=True)
    top_k: int = Field(default=5)
    score_threshold: float = Field(default=0.6)  # ngưỡng điểm thấp nhất để chấp nhận kết quả

    # ── Fulltext index state ──────────────────────────────────────────────
    _fulltext_ready: bool = False  # chỉ cần tạo index 1 lần
    _FULLTEXT_INDEX_NAME: str = "legal_fulltext_index"

    # ══════════════════════════════════════════════════════════════════════
    # Cypher queries cho 3 chiến lược
    # ══════════════════════════════════════════════════════════════════════

    # ── Nhánh 1: Keyword search (Fulltext Index — Lucene) ──────────────────
    # Dùng db.index.fulltext.queryNodes thay vì CONTAINS → O(log n) thay vì O(n)
    _CYPHER_KEYWORD = """
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $keyword)
    YIELD node, score
    WHERE score > 0.5
    WITH node, score
    LIMIT $top_k
    OPTIONAL MATCH (node)-[r]-(related)
    WHERE type(r) IN [
        'QUY_DINH_TAI', 'DAN_DEN_HAU_QUA', 'DIEU_KIEN_KICH_HOAT',
        'AP_DUNG_CHO', 'THAM_CHIEU_DEN', 'TRONG_TRUONG_HOP',
        'DOI_VOI', 'NHOM_HANH_VI', 'THUOC', 'THUC_HIEN',
        'NGOAI_TRU', 'THAY_THE_CHO', 'UU_TIEN_AP_DUNG', 'VA'
    ]
    RETURN
        node.id         AS id,
        node.text       AS text,
        node.raw_text   AS raw_content,
        node.name       AS name,
        labels(node)[0] AS label,
        collect(DISTINCT {
            rel_type:    type(r),
            related_id:  related.id,
            related_name: related.name,
            related_text: related.raw_text
        }) AS relationships,
        score,
        'keyword' AS source
    ORDER BY score DESC
    """

    # ── Nhánh 2: Vector search (semantic embedding) ──────────────────────
    _CYPHER_VECTOR = """
    CALL db.index.vector.queryNodes('legal_vector_index', $top_k, $vector)
    YIELD node, score
    OPTIONAL MATCH (node)-[r]-(related)
    WHERE type(r) IN [
        'QUY_DINH_TAI', 'DAN_DEN_HAU_QUA', 'DIEU_KIEN_KICH_HOAT',
        'AP_DUNG_CHO', 'THAM_CHIEU_DEN', 'TRONG_TRUONG_HOP',
        'DOI_VOI', 'NHOM_HANH_VI', 'THUOC', 'THUC_HIEN',
        'NGOAI_TRU', 'THAY_THE_CHO', 'UU_TIEN_AP_DUNG', 'VA'
    ]
    RETURN
        node.id         AS id,
        node.text       AS text,
        node.raw_text   AS raw_content,
        node.name       AS name,
        labels(node)[0] AS label,
        collect(DISTINCT {
            rel_type:    type(r),
            related_id:  related.id,
            related_name: related.name,
            related_text: related.raw_text
        }) AS relationships,
        score,
        'vector' AS source
    ORDER BY score DESC
    """

    # ── Nhánh 3: Graph traversal (entity-driven) ─────────────────────────
    # Tìm Action node khớp với violation, rồi traverse ra tất cả relationships
    _CYPHER_GRAPH = """
    MATCH (action:Action)
    WHERE toLower(action.name) CONTAINS toLower($violation)
       OR toLower(action.text) CONTAINS toLower($violation)
    WITH action
    LIMIT $top_k

    OPTIONAL MATCH (action)-[:QUY_DINH_TAI]->(article:Article)
    OPTIONAL MATCH (action)-[:DAN_DEN_HAU_QUA]->(consequence:Consequence)
    OPTIONAL MATCH (action)-[:DIEU_KIEN_KICH_HOAT]->(condition:Condition)
    OPTIONAL MATCH (action)-[:AP_DUNG_CHO]->(subject:Subject)
    OPTIONAL MATCH (action)-[:TRONG_TRUONG_HOP]->(context_cond:Condition)
    OPTIONAL MATCH (article)-[:THAM_CHIEU_DEN]->(ref_article:Article)

    RETURN
        action.id         AS id,
        action.text       AS text,
        action.raw_text   AS raw_content,
        action.name       AS name,
        'Action'          AS label,
        collect(DISTINCT {rel_type: 'QUY_DINH_TAI',       related_id: article.id,      related_name: article.name,      related_text: article.raw_text})
      + collect(DISTINCT {rel_type: 'DAN_DEN_HAU_QUA',    related_id: consequence.id,  related_name: consequence.name,  related_text: consequence.raw_text})
      + collect(DISTINCT {rel_type: 'DIEU_KIEN_KICH_HOAT',related_id: condition.id,    related_name: condition.name,    related_text: condition.raw_text})
      + collect(DISTINCT {rel_type: 'AP_DUNG_CHO',        related_id: subject.id,      related_name: subject.name,      related_text: subject.raw_text})
      + collect(DISTINCT {rel_type: 'TRONG_TRUONG_HOP',   related_id: context_cond.id, related_name: context_cond.name, related_text: context_cond.raw_text})
      + collect(DISTINCT {rel_type: 'THAM_CHIEU_DEN',     related_id: ref_article.id,  related_name: ref_article.name,  related_text: ref_article.raw_text})
        AS relationships,
        0.8 AS score,
        'graph' AS source
    ORDER BY action.id
    """

    # ── Nhánh 3b: Graph traversal bổ sung theo Subject (vehicle_type) ────
    _CYPHER_GRAPH_SUBJECT = """
    MATCH (subj:Subject)
    WHERE toLower(subj.name) CONTAINS toLower($vehicle_type)
    WITH subj
    LIMIT 3
    MATCH (node)-[:AP_DUNG_CHO]->(subj)
    WHERE toLower(node.name) CONTAINS toLower($violation)
       OR toLower(node.text) CONTAINS toLower($violation)
    WITH node, subj
    LIMIT $top_k

    OPTIONAL MATCH (node)-[r]-(related)
    WHERE type(r) IN [
        'QUY_DINH_TAI', 'DAN_DEN_HAU_QUA', 'DIEU_KIEN_KICH_HOAT',
        'TRONG_TRUONG_HOP', 'DOI_VOI', 'NHOM_HANH_VI'
    ]
    RETURN
        node.id         AS id,
        node.text       AS text,
        node.raw_text   AS raw_content,
        node.name       AS name,
        labels(node)[0] AS label,
        collect(DISTINCT {
            rel_type:    type(r),
            related_id:  related.id,
            related_name: related.name,
            related_text: related.raw_text
        }) AS relationships,
        0.85 AS score,
        'graph_subject' AS source
    ORDER BY node.id
    """

    # ══════════════════════════════════════════════════════════════════════
    # Relationship label → tên tiếng Việt (dùng khi format output)
    # ══════════════════════════════════════════════════════════════════════
    _REL_LABELS = {
        "QUY_DINH_TAI":        "📋 Quy định tại",
        "DAN_DEN_HAU_QUA":     "⚖️ Hậu quả / Mức phạt",
        "DIEU_KIEN_KICH_HOAT": "🔑 Điều kiện kích hoạt",
        "AP_DUNG_CHO":         "👤 Áp dụng cho",
        "THAM_CHIEU_DEN":      "🔗 Tham chiếu đến",
        "TRONG_TRUONG_HOP":    "📌 Trong trường hợp",
        "DOI_VOI":             "🎯 Đối với",
        "NHOM_HANH_VI":        "📂 Nhóm hành vi",
        "THUOC":               "🏷️ Thuộc",
        "THUC_HIEN":           "✅ Thực hiện",
        "NGOAI_TRU":           "🚫 Ngoại trừ",
        "THAY_THE_CHO":        "🔄 Thay thế cho",
        "UU_TIEN_AP_DUNG":     "⭐ Ưu tiên áp dụng",
        "VA":                  "➕ Và",
    }

    # ------------------------------------------------------------------
    # Query logging — ghi kết quả Neo4j ra file txt
    # ------------------------------------------------------------------

    # Thư mục log: ai-service/logs/ (tạo tự động nếu chưa có)
    _LOG_DIR: Path = Path(__file__).parent.parent.parent / "logs"

    def _write_query_log(self, query: str, entities: dict, context: str) -> None:
        """Ghi query + context từ Neo4j ra file txt theo ngày."""
        try:
            self._LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = self._LOG_DIR / f"neo4j_query_{datetime.now().strftime('%Y-%m-%d')}.txt"
            sep = "=" * 70
            entry = (
                f"\n{sep}\n"
                f"[{datetime.now().strftime('%H:%M:%S')}] QUERY: {query}\n"
                f"  vehicle_type : {entities.get('vehicle_type', '')}\n"
                f"  violation    : {entities.get('violation', '')}\n"
                f"  conditions   : {entities.get('conditions', [])}\n"
                f"  subject      : {entities.get('subject', '')}\n"
                f"--- CONTEXT ({len(context)} chars) ---\n"
                f"{context}\n"
                f"{sep}\n"
            )
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as exc:
            logging.warning(f"[GraphRetrievalTool] Không ghi được log: {exc}")

    # ------------------------------------------------------------------
    # Core logic (private)
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list:
        """Tạo vector embedding (CPU-bound, chạy trong executor)."""
        return self.embed_model.encode(text).tolist()

    # ------------------------------------------------------------------
    # Fulltext Index — auto-create nếu chưa tồn tại
    # ------------------------------------------------------------------
    async def _ensure_fulltext_index(self) -> None:
        """
        Tạo fulltext index trên Neo4j nếu chưa có.

        Index bao phủ 6 node labels × 3 properties (name, text, raw_text).
        Dùng Apache Lucene analyzer → hỗ trợ tiếng Việt (unaccented search,
        tokenization tốt hơn CONTAINS).

        Chỉ chạy 1 lần duy nhất trong vòng đời của tool instance.
        Nếu index đã tồn tại → Neo4j tự bỏ qua (idempotent).
        """
        if self._fulltext_ready:
            return

        create_index_cypher = """
        CREATE FULLTEXT INDEX legal_fulltext_index IF NOT EXISTS
        FOR (n:Article|Action|Consequence|Condition|Subject|Entity)
        ON EACH [n.name, n.text, n.raw_text]
        OPTIONS {
            indexConfig: {
                `fulltext.analyzer`: 'standard-no-stop-words',
                `fulltext.eventually_consistent`: true
            }
        }
        """

        try:
            async with self.driver.session(
                database="neo4j",
                default_access_mode=neo4j.WRITE_ACCESS,
            ) as session:
                await session.run(create_index_cypher)
                logging.info(
                    f"✅ Fulltext index '{self._FULLTEXT_INDEX_NAME}' "
                    f"đã sẵn sàng (6 labels × 3 properties)."
                )
            self._fulltext_ready = True
        except Exception as e:
            logging.warning(
                f"⚠️ Không thể tạo fulltext index: {e}. "
                f"Keyword search vẫn hoạt động nếu index đã tồn tại."
            )
            # Vẫn đánh dấu ready để không retry liên tục
            self._fulltext_ready = True

    # ------------------------------------------------------------------
    # Nhánh 1: Keyword search (Fulltext Index)
    # ------------------------------------------------------------------
    async def _search_keyword(self, keyword: str) -> list[dict]:
        """
        Tìm kiếm theo từ khóa qua Fulltext Index (Lucene).

        Tại sao dùng Fulltext Index thay vì CONTAINS?
        ─────────────────────────────────────────────────
        - CONTAINS → full scan O(n) trên toàn bộ node, rất chậm khi graph nở.
        - Fulltext Index → Lucene inverted index, O(log n).
        - Hỗ trợ fuzzy matching, tokenization, scoring tự nhiên.
        """
        if not keyword or not keyword.strip():
            return []

        # Đảm bảo index tồn tại trước khi query
        await self._ensure_fulltext_index()

        try:
            async with self.driver.session(
                database="neo4j",
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                result = await session.run(
                    self._CYPHER_KEYWORD,
                    keyword=keyword.strip(),
                    top_k=self.top_k,
                )
                records = await result.data()
                logging.info(f"[Keyword/Fulltext] Tìm được {len(records)} node cho '{keyword[:50]}'")
                return records
        except Exception as e:
            logging.error(f"[Keyword/Fulltext] Lỗi: {e}")
            return []

    # ------------------------------------------------------------------
    # Nhánh 2: Vector search
    # ------------------------------------------------------------------
    async def _search_vector(self, vector: list) -> list[dict]:
        """Tìm kiếm theo vector embedding (semantic similarity)."""
        if not vector:
            return []

        try:
            async with self.driver.session(
                database="neo4j",
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                result = await session.run(
                    self._CYPHER_VECTOR,
                    vector=vector,
                    top_k=self.top_k,
                )
                records = await result.data()
                logging.info(f"[Vector] Tìm được {len(records)} node")
                return records
        except Exception as e:
            logging.error(f"[Vector] Lỗi: {e}")
            return []

    # ------------------------------------------------------------------
    # Nhánh 3: Graph traversal (entity-driven)
    # ------------------------------------------------------------------
    async def _search_graph(self, entities: dict) -> list[dict]:
        """Duyệt đồ thị dựa trên entities đã bóc tách."""
        violation = (entities.get("violation") or "").strip()
        vehicle_type = (entities.get("vehicle_type") or "").strip()

        if not violation:
            return []

        try:
            async with self.driver.session(
                database="neo4j",
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                tasks = []

                # 3a: Traversal theo violation (Action → relationships)
                result_main = await session.run(
                    self._CYPHER_GRAPH,
                    violation=violation,
                    top_k=self.top_k,
                )
                records_main = await result_main.data()

                # 3b: Nếu có vehicle_type, thu hẹp theo Subject
                records_subject = []
                if vehicle_type:
                    result_subj = await session.run(
                        self._CYPHER_GRAPH_SUBJECT,
                        violation=violation,
                        vehicle_type=vehicle_type,
                        top_k=self.top_k,
                    )
                    records_subject = await result_subj.data()

                all_records = records_main + records_subject
                logging.info(
                    f"[Graph] Tìm được {len(records_main)} node (violation) "
                    f"+ {len(records_subject)} node (subject filter) "
                    f"cho violation='{violation[:50]}'"
                )
                return all_records

        except Exception as e:
            logging.error(f"[Graph] Lỗi: {e}")
            return []

    # ------------------------------------------------------------------
    # Merge, deduplicate, rank
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_results(
        keyword_results: list[dict],
        vector_results: list[dict],
        graph_results: list[dict],
    ) -> list[dict]:
        """
        Gộp kết quả từ 3 nhánh, deduplicate theo node.id, rank theo tổng điểm.

        Scoring:
          - keyword hit  : +0.3  (đánh giá cao exact match)
          - vector score : score * 0.5 (normalized cosine sim)
          - graph hit    : +0.2  (structural relevance)
          - Bonus nếu xuất hiện ở cả 3 nguồn: +0.1

        ⚠️ QUAN TRỌNG: Keyword scores từ Lucene không giới hạn [0,1] (có thể lên đến 20-30)
        → Normalize về [0,1] trước khi merge để threshold logic hoạt động đúng
        """
        # ── Bước 0: Normalize Lucene keyword scores về [0,1] ─────────────────
        if keyword_results:
            max_keyword_score = max(r.get("score", 0) or 0 for r in keyword_results)
            if max_keyword_score > 1.0:  # Chỉ normalize khi cần thiết
                for r in keyword_results:
                    original_score = r.get("score", 0) or 0
                    r["score"] = original_score / max_keyword_score
                    r["_original_lucene_score"] = original_score  # Debug info
                logging.info(
                    f"[Merge] Normalized keyword scores: max={max_keyword_score:.2f} → 1.0"
                )

        merged: dict[str, dict] = {}  # id → merged record

        def _add(records: list[dict], weight: float, source_name: str):
            for r in records:
                node_id = r.get("id")
                if not node_id:
                    continue

                raw_score = r.get("score", 0) or 0

                if node_id in merged:
                    existing = merged[node_id]
                    existing["_weighted_score"] += raw_score * weight
                    existing["_sources"].add(source_name)
                    # Merge thêm relationships nếu có mới
                    existing_rel_ids = {
                        rel.get("related_id") for rel in existing.get("relationships", [])
                    }
                    for rel in r.get("relationships", []):
                        if rel.get("related_id") and rel["related_id"] not in existing_rel_ids:
                            existing["relationships"].append(rel)
                            existing_rel_ids.add(rel["related_id"])
                else:
                    merged[node_id] = {
                        **r,
                        "_weighted_score": raw_score * weight,
                        "_sources": {source_name},
                    }

        # Áp dụng trọng số cho từng nguồn
        _add(keyword_results, weight=0.3, source_name="keyword")
        _add(vector_results,  weight=0.5, source_name="vector")
        _add(graph_results,   weight=0.2, source_name="graph")

        # Bonus nếu xuất hiện ở nhiều nguồn (multi-source boost)
        for record in merged.values():
            n_sources = len(record["_sources"])
            if n_sources >= 3:
                record["_weighted_score"] += 0.15  # xuất hiện cả 3 nguồn → rất liên quan
            elif n_sources >= 2:
                record["_weighted_score"] += 0.08  # xuất hiện 2 nguồn

        # Sắp xếp theo tổng điểm giảm dần
        sorted_results = sorted(
            merged.values(),
            key=lambda x: x["_weighted_score"],
            reverse=True,
        )

        return sorted_results

    # ------------------------------------------------------------------
    # Format context output (enhanced với relationships)
    # ------------------------------------------------------------------
    def _format_context(self, records: list[dict]) -> str:
        """Format kết quả thành context text cho LLM, bao gồm relationship info."""
        if not records:
            return ""

        context_blocks = []
        for r in records:
            sources = ", ".join(sorted(r.get("_sources", set())))
            score = r.get("_weighted_score", 0)
            label = r.get("label", "Unknown")
            name = r.get("name", "")

            # Header block
            block = f"--- Nguồn {r['id']} (score: {score:.3f} | loại: {label} | từ: {sources}) ---\n"

            if name:
                block += f"Tên: {name}\n"

            # Nội dung chính
            raw_content = r.get("raw_content") or r.get("text") or ""
            if raw_content:
                block += f"{raw_content}\n"

            # Relationships (thông tin liên kết đồ thị)
            relationships = r.get("relationships", [])
            # Lọc bỏ relationships rỗng (related_id = None)
            valid_rels = [
                rel for rel in relationships
                if rel.get("related_id") is not None
            ]

            if valid_rels:
                block += "\n  ── Quan hệ đồ thị ──\n"
                # Nhóm theo rel_type
                grouped: dict[str, list] = {}
                for rel in valid_rels:
                    rel_type = rel.get("rel_type", "UNKNOWN")
                    if rel_type not in grouped:
                        grouped[rel_type] = []
                    grouped[rel_type].append(rel)

                for rel_type, rels in grouped.items():
                    label_vi = self._REL_LABELS.get(rel_type, f"🔹 {rel_type}")
                    block += f"  {label_vi}:\n"
                    for rel in rels:
                        rel_name = rel.get("related_name", "")
                        rel_text = rel.get("related_text", "")
                        if rel_text:
                            # Giới hạn text ngắn gọn
                            snippet = rel_text[:500] + "..." if len(rel_text) > 500 else rel_text
                            block += f"    • [{rel.get('related_id', '')}] {rel_name}: {snippet}\n"
                        elif rel_name:
                            block += f"    • [{rel.get('related_id', '')}] {rel_name}\n"

            context_blocks.append(block)

        return "\n\n".join(context_blocks)

    # ------------------------------------------------------------------
    # LangChain interface — sync (bắt buộc override)
    # ------------------------------------------------------------------

    def _run(
        self,
        query: str,
        entities: dict = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Sync fallback — chạy async trong event loop mới nếu không có sẵn."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Đang trong async context → chạy coroutine trực tiếp
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._arun(query, entities))
                    return future.result()
            else:
                return loop.run_until_complete(self._arun(query, entities))
        except Exception as e:
            logging.error(f"[GraphRetrievalTool] Lỗi sync: {e}")
            return f"Lỗi khi tra cứu: {e}"

    # ------------------------------------------------------------------
    # LangChain interface — async (ưu tiên dùng)
    # ------------------------------------------------------------------

    async def _arun(
        self,
        query: str,
        entities: dict = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """
        Async entry point — chạy 3 nhánh search SONG SONG.

        Parameters
        ----------
        query : str
            Thuật ngữ pháp lý đã chuẩn hóa (legal_query từ router).
        entities : dict, optional
            Entities đã bóc tách: {violation, vehicle_type, subject, conditions[]}.

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

        entities = entities or {}

        try:
            # ── Bước 1: Tạo embedding (CPU-bound → executor) ─────────────
            loop = asyncio.get_running_loop()
            vector = await loop.run_in_executor(None, self._embed, query)

            # ── Bước 2: Chạy SONG SONG 3 nhánh ──────────────────────────
            logging.info(
                f"[GraphRetrievalTool] 🚀 Bắt đầu parallel search: "
                f"keyword='{query[:50]}' | "
                f"violation='{entities.get('violation', '')[:50]}' | "
                f"vehicle='{entities.get('vehicle_type', '')}'"
            )

            keyword_task = self._search_keyword(query)
            vector_task  = self._search_vector(vector)
            graph_task   = self._search_graph(entities)

            keyword_results, vector_results, graph_results = await asyncio.gather(
                keyword_task,
                vector_task,
                graph_task,
                return_exceptions=True,
            )

            # Xử lý exceptions từ gather
            if isinstance(keyword_results, Exception):
                logging.error(f"[Keyword] Exception: {keyword_results}")
                keyword_results = []
            if isinstance(vector_results, Exception):
                logging.error(f"[Vector] Exception: {vector_results}")
                vector_results = []
            if isinstance(graph_results, Exception):
                logging.error(f"[Graph] Exception: {graph_results}")
                graph_results = []

            logging.info(
                f"[GraphRetrievalTool] ✅ Parallel search hoàn tất: "
                f"keyword={len(keyword_results)} | "
                f"vector={len(vector_results)} | "
                f"graph={len(graph_results)}"
            )

            # ── Bước 3: Merge + Deduplicate + Rank ───────────────────────
            merged = self._merge_results(keyword_results, vector_results, graph_results)

            if not merged:
                not_found_msg = (
                    "Không tìm thấy thông tin liên quan trong cơ sở dữ liệu đồ thị. "
                    "Câu hỏi có thể nằm ngoài phạm vi Nghị định 168/2024/NĐ-CP."
                )
                self._write_query_log(query, entities, "(KHÔNG TÌM THẤY KẾT QUẢ)")
                return not_found_msg

            # ── Bước 3.5: THRESHOLDING — kiểm tra chất lượng kết quả ─────
            # Nếu điểm cao nhất vẫn dưới ngưỡng → Graph "đầu hàng" và signal cho Web Search
            max_score = merged[0].get("_weighted_score", 0) if merged else 0

            if max_score < self.score_threshold:
                low_confidence_msg = (
                    f"⚠️ [LOW_CONFIDENCE_THRESHOLD] Kết quả từ đồ thị có độ tin cậy thấp "
                    f"(max_score={max_score:.3f} < threshold={self.score_threshold}). "
                    f"Dữ liệu có thể chưa cập nhật hoặc không đủ chi tiết. "
                    f"Nên chuyển sang tìm kiếm web để bổ sung."
                )
                logging.warning(
                    f"[GraphRetrievalTool] Threshold check failed: "
                    f"max_score={max_score:.3f} < {self.score_threshold}"
                )
                self._write_query_log(query, entities, low_confidence_msg)
                return low_confidence_msg

            # ── Bước 4: Format context ───────────────────────────────────
            # Giới hạn top kết quả sau merge (tránh quá nhiều)
            max_results = self.top_k * 2  # cho phép nhiều hơn mỗi nhánh 1 chút
            context = self._format_context(merged[:max_results])

            # ── Ghi log ra file ───────────────────────────────────────────
            self._write_query_log(query, entities, context)

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
    score_threshold: float = 0.6,
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
        Số lượng node tìm kiếm tối đa mỗi nhánh.
    score_threshold : float
        Ngưỡng điểm tối thiểu để chấp nhận kết quả (mặc định: 0.6).
        Nếu max_score < threshold → Graph "đầu hàng" và signal cho Web Search.

    Returns
    -------
    GraphRetrievalTool
        Tool sẵn sàng bind vào LangChain agent.

    Example
    -------
    >>> tool = make_graph_retrieval_tool(driver, embed_model, top_k=5, score_threshold=0.6)
    >>> agent = create_react_agent(llm, tools=[tool], checkpointer=checkpointer)
    """
    return GraphRetrievalTool(
        driver=driver,
        embed_model=embed_model,
        top_k=top_k,
        score_threshold=score_threshold,
    )
