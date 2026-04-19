"""
app/tools/graph_retrieval.py
────────────────────────────
Đóng gói chức năng truy xuất đồ thị tri thức (Neo4j) thành LangChain Tool chuẩn.

Chiến lược retrieval 4-prong SONG SONG với RRF:
───────────────────────────────────────────────
  1. Keyword search      — Fulltext Index (Lucene) thay vì CONTAINS → O(log n)
  2. Vector search       — tìm theo ngữ nghĩa tương đồng (embedding cosine)
  3. Graph traversal     — duyệt đồ thị qua Fulltext Index + entity-driven
  4. Consequence-first   — tìm Consequence nodes trước, traverse ngược về Action

Bốn nhánh chạy đồng thời qua asyncio.gather với timeout guards,
sau đó merge bằng RRF (Reciprocal Rank Fusion).

Post-Processing Enhancement:
────────────────────────────
  ✅ Vehicle-Aware Boosting — Nhân điểm 1.3x cho kết quả khớp loại xe (trong Nghị định 168)

Performance Optimizations:
─────────────────────────
  ✅ RRF (Reciprocal Rank Fusion) — Không cần normalize scores từ nguồn khác nhau
  ✅ Fulltext Index thay CONTAINS — O(log n) thay vì O(n) full scan
  ✅ Parallel Execution — 4 nhánh chạy đồng thời
  ✅ Timeout Guards — Bảo vệ khỏi slow queries, mỗi nhánh có timeout riêng

Cách dùng trong agentic flow:
─────────────────────────────
    from app.tools.graph_retrieval import make_graph_retrieval_tool

    tool = make_graph_retrieval_tool(
        driver=driver,
        embed_model=embed_model,
        keyword_timeout=3.0,
        vector_timeout=5.0,
        graph_timeout=5.0,
        consequence_timeout=3.0,
        vehicle_boost_enabled=True,
        vehicle_boost_multiplier=1.3
    )
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
from langchain_core.callbacks import (
    CallbackManagerForToolRun,
    AsyncCallbackManagerForToolRun,
)
from pydantic import BaseModel, Field
import re
from app.core.config import settings

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Pattern Detection & Keyword Extraction for Consequence-First Queries
# ══════════════════════════════════════════════════════════════════════

# Patterns to detect consequence-first queries (queries starting from penalties/fines)
CONSEQUENCE_PATTERNS = {
    "fine_amount": [
        r"phạt\s+(\d+)\s*(triệu|tr|nghìn|ngàn|đồng)",  # "phạt 5 triệu"
        r"mức\s+phạt\s+(\d+)",  # "mức phạt 5 triệu"
        r"(\d+)\s*(triệu|tr|nghìn)\s+(lỗi|vi phạm|phạt)",  # "5 triệu lỗi gì" or "8 triệu phạt lỗi gì"
    ],
    "license_suspension": [
        r"tước\s+(giấy phép|bằng|gplx)\s+(\d+)\s*(tháng|năm)",  # "tước bằng 3 tháng"
        r"bị\s+tước\s+bằng",  # "bị tước bằng"
    ],
    "points_deduction": [
        r"trừ\s+(\d+)\s*điểm",  # "trừ 4 điểm"
        r"bị\s+trừ\s+điểm",  # "bị trừ điểm"
    ],
}


def _detect_consequence_query(query: str) -> bool:
    """
    Check if query is asking about consequences first (fines, penalties, license suspension).

    Parameters
    ----------
    query : str
        User query to analyze.

    Returns
    -------
    bool
        True if query matches any consequence pattern, False otherwise.
    """
    query_lower = query.lower()
    for category, patterns in CONSEQUENCE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                return True
    return False


def _extract_consequence_keyword(query: str) -> str:
    """
    Extract search keyword for Consequence nodes from query.

    Priority order:
    1. Explicit fine amounts: "5 triệu" → "Phạt tiền 5.000.000"
    2. License suspension: "tước bằng 3 tháng" → "tước giấy phép 3 tháng"
    3. Points deduction: "trừ 4 điểm" → "trừ điểm 04 điểm"
    4. General consequence terms: fallback to original query

    Parameters
    ----------
    query : str
        User query containing consequence terms.

    Returns
    -------
    str
        Optimized keyword for searching Consequence nodes.
    """
    query_lower = query.lower()

    # Priority 1: Extract fine amounts
    fine_match = re.search(r"(\d+)\s*(triệu|tr)", query_lower)
    if fine_match:
        amount = int(fine_match.group(1))
        return f"Phạt tiền {amount}.000.000 đồng"

    # Priority 2: License suspension duration
    license_match = re.search(
        r"tước.*(bằng|giấy phép|gplx).*?(\d+)\s*(tháng|năm)", query_lower
    )
    if license_match:
        duration = license_match.group(2)
        unit = license_match.group(3)
        return f"tước quyền sử dụng giấy phép lái xe {duration} {unit}"

    # Priority 3: Points deduction
    points_match = re.search(r"trừ.*?(\d+)\s*điểm", query_lower)
    if points_match:
        points = points_match.group(1).zfill(2)  # "4" → "04"
        return f"trừ điểm giấy phép lái xe {points} điểm"

    # Fallback: use original query
    return query


def _escape_lucene(text: str) -> str:
    """Escape Lucene special characters to prevent TokenMgrError in fulltext queries."""
    if not text:
        return ""
    # Lucene special chars: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
    special = r'[+\-&|!(){}\[\]^"~*?:\\/]'
    return re.sub(special, r"\\\g<0>", text)


# ══════════════════════════════════════════════════════════════════════
# Vehicle Type Normalization and Aliases for Vehicle-Aware Boosting
# ══════════════════════════════════════════════════════════════════════

VEHICLE_ALIASES = {
    "xe máy": ["xe máy", "mô tô", "xe mô tô", "xe gắn máy"],
    "ô tô": ["ô tô", "xe ô tô", "xe con"],
    "xe tải": ["xe tải", "xe chở hàng", "xe chở hàng bốn bánh"],
    "xe khách": ["xe khách", "xe chở người", "xe bus"],
    "xe đạp điện": ["xe đạp điện", "xe máy điện"],
}


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
        ),
    )


# ---------------------------------------------------------------------------
# Tool class (hỗ trợ cả sync và async)
# ---------------------------------------------------------------------------


class GraphRetrievalTool(BaseTool):
    """
    LangChain Tool tra cứu đồ thị tri thức pháp lý.

    Thực hiện SONG SONG 3 chiến lược với timeout guards:
      1. Keyword search  — Fulltext Index (Lucene) → O(log n)
      2. Vector search   — embedding cosine similarity → semantic match
      3. Graph traversal — Fulltext Index + entity-driven → structural match

    Kết quả 3 nhánh được merge bằng RRF (Reciprocal Rank Fusion):
      RRF_score(node) = Σ 1/(60 + rank_i)

    Attributes
    ----------
    driver : neo4j.AsyncDriver
        Driver Neo4j async đã được khởi tạo sẵn.
    embed_model : SentenceTransformer
        Model embedding đã được load sẵn.
    top_k : int
        Số node tìm kiếm tối đa mỗi nhánh (mặc định: 5).
    keyword_timeout : float
        Timeout (giây) cho Fulltext keyword search (mặc định: 3.0s).
    vector_timeout : float
        Timeout (giây) cho Vector semantic search (mặc định: 5.0s).
    graph_timeout : float
        Timeout (giây) cho Graph traversal (mặc định: 5.0s).
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
    score_threshold: float = Field(
        default=0.6
    )  # ngưỡng điểm thấp nhất để chấp nhận kết quả

    # ── Timeout configuration (seconds) ───────────────────────────────────
    keyword_timeout: float = Field(default=3.0)  # Fulltext search nhanh, timeout thấp
    vector_timeout: float = Field(default=5.0)  # Vector search có thể chậm hơn
    graph_timeout: float = Field(default=5.0)  # Graph traversal có thể phức tạp
    consequence_timeout: float = Field(
        default=3.0
    )  # Consequence-first branch (fast, like keyword)

    # ── RRF Threshold configuration ───────────────────────────────────────
    # RRF Score Reference (k=60):
    #   - Top-1 cả 3 nguồn  : ~0.049 (max possible)
    #   - Top-1 hai nguồn   : ~0.033
    #   - Top-1 một nguồn   : ~0.016
    #   - Top-5 một nguồn   : ~0.015
    # Recommended: 0.025 (strict) | 0.016 (balanced) | 0.010 (lenient)
    rrf_threshold: float = Field(default=0.016)

    # ── Vehicle-Aware Boosting configuration ──────────────────────────────
    vehicle_boost_enabled: bool = Field(
        default=True,
        description="Enable vehicle-type aware score boosting for results matching user's vehicle type",
    )
    vehicle_boost_multiplier: float = Field(
        default=1.3,
        description="Score multiplier for vehicle-matching results (recommended: 1.3)",
    )

    # ── Fulltext index state ──────────────────────────────────────────────
    _fulltext_ready: bool = False  # chỉ cần tạo index 1 lần
    _FULLTEXT_INDEX_NAME: str = "legal_fulltext_index"

    # ══════════════════════════════════════════════════════════════════════
    # Cypher queries cho 3 chiến lược
    # ══════════════════════════════════════════════════════════════════════

    # ── Nhánh 1: Keyword search (Fulltext Index — Lucene) ──────────────────
    # Dùng db.index.fulltext.queryNodes thay vì CONTAINS → O(log n) thay vì O(n)
    # Note: Không filter theo score ở đây, để RRF xử lý ranking/filtering
    _CYPHER_KEYWORD = """
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $keyword)
    YIELD node, score
    WITH node, score
    ORDER BY score DESC
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

    # ── Nhánh 3: Graph traversal (entity-driven, using Fulltext Index) ───
    # Tìm Action node khớp với violation qua Fulltext Index, rồi traverse
    # Note: Không filter theo score, để RRF xử lý ranking
    _CYPHER_GRAPH = """
    // Bước 1: Tìm Action nodes qua Fulltext Index (thay vì CONTAINS)
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $violation)
    YIELD node, score
    WHERE 'Action' IN labels(node)
    WITH node AS action, score
    ORDER BY score DESC
    LIMIT $top_k

    // Bước 2: Traverse relationships từ Action nodes tìm được
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
        score,
        'graph' AS source
    ORDER BY score DESC
    """

    # ── Nhánh 3b: Graph traversal bổ sung theo Subject (vehicle_type, using Fulltext) ────
    # Note: Không filter theo score, để RRF xử lý ranking
    _CYPHER_GRAPH_SUBJECT = """
    // Bước 1: Tìm Subject nodes qua Fulltext Index
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $vehicle_type)
    YIELD node AS subj, score AS subj_score
    WHERE 'Subject' IN labels(subj)
    WITH subj, subj_score
    ORDER BY subj_score DESC
    LIMIT 3

    // Bước 2: Tìm nodes liên kết với Subject này
    MATCH (node)-[:AP_DUNG_CHO]->(subj)
    WITH node, subj, subj_score

    // Bước 3: Filter nodes theo violation qua Fulltext Index
    // Note: Đã bỏ score filter - let RRF handle ranking
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $violation)
    YIELD node AS violation_node, score AS violation_score
    WHERE violation_node.id = node.id
    WITH node, subj, violation_score
    ORDER BY violation_score DESC
    LIMIT $top_k

    // Bước 4: Traverse relationships
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
        violation_score AS score,
        'graph_subject' AS source
    ORDER BY violation_score DESC
    """

    # ── Nhánh 4: Consequence-First Lookup (Backward Traversal) ───────────────
    # Tìm Consequence nodes trước, sau đó traverse ngược về Action nodes.
    # Kích hoạt khi phát hiện query hỏi về mức phạt/hậu quả (e.g., "phạt 5 triệu lỗi gì?").
    _CYPHER_CONSEQUENCE_FIRST = """
    // Step 1: Search Consequence nodes via Fulltext Index
    CALL db.index.fulltext.queryNodes('legal_fulltext_index', $consequence_keyword)
    YIELD node, score
    WHERE 'Consequence' IN labels(node)
    WITH node AS consequence, score
    ORDER BY score DESC
    LIMIT $top_k

    // Step 2: Find Action nodes that point TO this Consequence (backward traversal)
    MATCH (action:Action)-[:DAN_DEN_HAU_QUA]->(consequence)

    // Step 3: Gather full context from Action node
    OPTIONAL MATCH (action)-[:QUY_DINH_TAI]->(article:Article)
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
        score,
        'consequence_first' AS source
    ORDER BY score DESC
    """

    # ══════════════════════════════════════════════════════════════════════
    # Relationship label → tên tiếng Việt (dùng khi format output)
    # ══════════════════════════════════════════════════════════════════════
    _REL_LABELS = {
        "QUY_DINH_TAI": "📋 Quy định tại",
        "DAN_DEN_HAU_QUA": "⚖️ Hậu quả / Mức phạt",
        "DIEU_KIEN_KICH_HOAT": "🔑 Điều kiện kích hoạt",
        "AP_DUNG_CHO": "👤 Áp dụng cho",
        "THAM_CHIEU_DEN": "🔗 Tham chiếu đến",
        "TRONG_TRUONG_HOP": "📌 Trong trường hợp",
        "DOI_VOI": "🎯 Đối với",
        "NHOM_HANH_VI": "📂 Nhóm hành vi",
        "THUOC": "🏷️ Thuộc",
        "THUC_HIEN": "✅ Thực hiện",
        "NGOAI_TRU": "🚫 Ngoại trừ",
        "THAY_THE_CHO": "🔄 Thay thế cho",
        "UU_TIEN_AP_DUNG": "⭐ Ưu tiên áp dụng",
        "VA": "➕ Và",
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
            log_file = (
                self._LOG_DIR / f"neo4j_query_{datetime.now().strftime('%Y-%m-%d')}.txt"
            )
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
                database=settings.NEO4J_DATABASE,
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
        escaped_keyword = _escape_lucene(keyword.strip())

        try:
            async with self.driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                result = await session.run(
                    self._CYPHER_KEYWORD,
                    keyword=escaped_keyword,
                    top_k=self.top_k,
                )
                records = await result.data()
                logging.info(
                    f"[Keyword/Fulltext] Tìm được {len(records)} node cho '{keyword[:50]}'"
                )
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
                database=settings.NEO4J_DATABASE,
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
        escaped_violation = _escape_lucene(violation)
        escaped_vehicle_type = _escape_lucene(vehicle_type)

        if not violation:
            return []

        try:
            async with self.driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                tasks = []

                # 3a: Traversal theo violation (Action → relationships)
                result_main = await session.run(
                    self._CYPHER_GRAPH,
                    violation=escaped_violation,
                    top_k=self.top_k,
                )
                records_main = await result_main.data()

                # 3b: Nếu có vehicle_type, thu hẹp theo Subject
                records_subject = []
                if vehicle_type:
                    result_subj = await session.run(
                        self._CYPHER_GRAPH_SUBJECT,
                        violation=escaped_violation,
                        vehicle_type=escaped_vehicle_type,
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
    # Nhánh 4: Consequence-First Lookup
    # ------------------------------------------------------------------
    async def _search_consequence_first(self, query: str, entities: dict) -> list[dict]:
        """
        Nhánh 4: Consequence-first lookup.

        Tìm Consequence nodes trước, sau đó traverse ngược về Action.
        Kích hoạt khi phát hiện query hỏi về mức phạt/hậu quả.

        Parameters
        ----------
        query : str
            Original user query.
        entities : dict
            Extracted entities (not used in detection, but available).

        Returns
        -------
        list[dict]
            List of Action nodes found via backward traversal from Consequences.
        """
        # Check if query is a consequence-first query
        if not _detect_consequence_query(query):
            return []  # Skip if not a consequence query

        consequence_keyword = _extract_consequence_keyword(query)
        escaped_consequence_keyword = _escape_lucene(consequence_keyword)

        logging.info(
            f"[ConsequenceFirst] Detected consequence query. "
            f"Keyword: {consequence_keyword}"
        )

        try:
            async with self.driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                result = await session.run(
                    self._CYPHER_CONSEQUENCE_FIRST,
                    consequence_keyword=escaped_consequence_keyword,
                    top_k=self.top_k,
                )
                records = await result.data()

                logging.info(
                    f"[ConsequenceFirst] Found {len(records)} Action nodes via backward traversal"
                )
                return records

        except Exception as e:
            logging.error(f"[ConsequenceFirst] Query failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Merge, deduplicate, rank using RRF (Reciprocal Rank Fusion)
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_results(
        keyword_results: list[dict],
        vector_results: list[dict],
        graph_results: list[dict],
        consequence_results: list[dict],  # NEW: 4th branch
    ) -> list[dict]:
        """
        Gộp kết quả từ 4 nhánh bằng RRF (Reciprocal Rank Fusion).

        Chiến lược mới: Keyword + Vector + Graph + ConsequenceFirst

        RRF Formula:
            RRF_score(node) = Σ 1/(k + rank_i)

        Trong đó:
          - k = 60 (constant, theo paper gốc của RRF)
          - rank_i = vị trí rank của node trong list thứ i (bắt đầu từ 1)
          - Tổng được tính trên tất cả các list mà node xuất hiện

        Ưu điểm của RRF:
          ✅ Không cần normalize scores từ các nguồn khác nhau
          ✅ Tự động cân bằng giữa precision (top results) và diversity
          ✅ Robust với outliers và score distributions khác nhau
          ✅ Đã được chứng minh hoạt động tốt trong IR (Information Retrieval)

        References:
          Cormack, G. V., Clarke, C. L., & Büttcher, S. (2009).
          "Reciprocal rank fusion outperforms condorcet and individual rank learning methods."
        """
        K_CONSTANT = 60  # RRF constant (tiêu chuẩn trong literature)

        # ── Bước 1: Build rank positions cho mỗi list ────────────────────────
        # Mỗi node trong mỗi list được gán rank position (1-indexed)
        rank_maps = {
            "keyword": {
                r.get("id"): idx + 1
                for idx, r in enumerate(keyword_results)
                if r.get("id")
            },
            "vector": {
                r.get("id"): idx + 1
                for idx, r in enumerate(vector_results)
                if r.get("id")
            },
            "graph": {
                r.get("id"): idx + 1
                for idx, r in enumerate(graph_results)
                if r.get("id")
            },
            "consequence_first": {
                r.get("id"): idx + 1
                for idx, r in enumerate(consequence_results)
                if r.get("id")
            },
        }

        # ── Bước 2: Build lookup cho full record data ────────────────────────
        # Để lấy thông tin chi tiết của node sau khi tính RRF
        all_records_by_id: dict[str, dict] = {}
        for r in keyword_results + vector_results + graph_results + consequence_results:
            node_id = r.get("id")
            if not node_id:
                continue
            if node_id not in all_records_by_id:
                all_records_by_id[node_id] = r

        # ── Bước 3: Tính RRF score cho mỗi node ──────────────────────────────
        rrf_scores: dict[str, float] = {}
        node_sources: dict[str, set] = {}  # Track nguồn nào có node này

        for source_name, rank_map in rank_maps.items():
            for node_id, rank in rank_map.items():
                # RRF contribution từ source này
                rrf_contribution = 1.0 / (K_CONSTANT + rank)

                if node_id not in rrf_scores:
                    rrf_scores[node_id] = 0.0
                    node_sources[node_id] = set()

                rrf_scores[node_id] += rrf_contribution
                node_sources[node_id].add(source_name)

        # ── Bước 4: Merge relationships từ tất cả sources ────────────────────
        merged_records: dict[str, dict] = {}

        for node_id, rrf_score in rrf_scores.items():
            # Lấy record base (từ source nào cũng được)
            base_record = all_records_by_id[node_id].copy()

            # Merge relationships từ tất cả sources
            all_relationships = []
            seen_rel_ids = set()

            for source_name, rank_map in rank_maps.items():
                if node_id in rank_map:
                    # Tìm record gốc từ source này
                    source_records = {
                        "keyword": keyword_results,
                        "vector": vector_results,
                        "graph": graph_results,
                    }[source_name]

                    for r in source_records:
                        if r.get("id") == node_id:
                            for rel in r.get("relationships", []):
                                rel_id = rel.get("related_id")
                                if rel_id and rel_id not in seen_rel_ids:
                                    all_relationships.append(rel)
                                    seen_rel_ids.add(rel_id)
                            break

            merged_records[node_id] = {
                **base_record,
                "relationships": all_relationships,
                "_rrf_score": rrf_score,
                "_sources": node_sources[node_id],
            }

        # ── Bước 5: Sắp xếp theo RRF score giảm dần ──────────────────────────
        sorted_results = sorted(
            merged_records.values(),
            key=lambda x: x["_rrf_score"],
            reverse=True,
        )

        top_scores = [f"{r.get('_rrf_score', 0):.4f}" for r in sorted_results[:3]]
        logging.info(
            f"[RRF Merge] Processed {len(sorted_results)} unique nodes. "
            f"Top-3 scores: {top_scores}"
        )

        return sorted_results

    # ------------------------------------------------------------------
    # Vehicle-Aware Boosting (Post-RRF)
    # ------------------------------------------------------------------
    def _apply_vehicle_boost(
        self, merged_results: list[dict], entities: dict
    ) -> list[dict]:
        """
        Apply vehicle-type aware boosting to RRF scores.

        Boosts results that have [:AP_DUNG_CHO] relationships matching
        the extracted vehicle_type from entities.

        Parameters
        ----------
        merged_results : list[dict]
            Results after RRF merge (with _rrf_score).
        entities : dict
            Extracted entities with 'vehicle_type' key.

        Returns
        -------
        list[dict]
            Re-sorted results after applying boost.
        """
        if not self.vehicle_boost_enabled:
            return merged_results

        vehicle_type = (entities.get("vehicle_type") or "").strip().lower()

        if not vehicle_type:
            return merged_results  # No boost if no vehicle specified

        # Normalize vehicle_type to canonical form
        canonical_vehicle = vehicle_type
        for canonical, aliases in VEHICLE_ALIASES.items():
            if vehicle_type in aliases:
                canonical_vehicle = canonical
                break

        # Apply boost
        boosted_count = 0
        for result in merged_results:
            relationships = result.get("relationships", [])

            # Check if this result has AP_DUNG_CHO relationship matching vehicle
            has_matching_vehicle = False
            for rel in relationships:
                if rel.get("rel_type") == "AP_DUNG_CHO":
                    subject_name = (rel.get("related_name") or "").lower()

                    # Check exact match or alias match
                    for alias in VEHICLE_ALIASES.get(
                        canonical_vehicle, [canonical_vehicle]
                    ):
                        if alias in subject_name:
                            has_matching_vehicle = True
                            break

                    if has_matching_vehicle:
                        break

            if has_matching_vehicle:
                original_score = result.get("_rrf_score", 0)
                boosted_score = original_score * self.vehicle_boost_multiplier
                result["_rrf_score"] = boosted_score
                result["_vehicle_boosted"] = True  # For debugging
                boosted_count += 1

                logging.info(
                    f"[VehicleBoost] {result['id']}: "
                    f"{original_score:.4f} → {boosted_score:.4f} "
                    f"(matched: {canonical_vehicle})"
                )

        if boosted_count > 0:
            # Re-sort by boosted scores
            merged_results = sorted(
                merged_results, key=lambda x: x.get("_rrf_score", 0), reverse=True
            )
            logging.info(
                f"[VehicleBoost] Boosted {boosted_count} results matching vehicle: {canonical_vehicle}"
            )

        return merged_results

    # ------------------------------------------------------------------
    # Format context output (enhanced với relationships)
    # ------------------------------------------------------------------
    def _format_context(self, records: list[dict]) -> str:
        """Format kết quả thành context XML cho LLM, bao gồm relationship info."""
        if not records:
            return ""

        def _xe(text: str) -> str:
            """Escape XML special characters."""
            if not text:
                return ""
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        context_blocks = []
        for r in records:
            sources = ",".join(sorted(r.get("_sources", set())))
            score = r.get("_rrf_score", 0)
            label = r.get("label", "Unknown")
            node_id = r.get("id", "")
            name = r.get("name", "")

            lines = [
                f'<source id="{_xe(node_id)}" score="{score:.3f}"'
                f' label="{_xe(label)}" from="{_xe(sources)}">'
            ]

            if name:
                lines.append(f"  <name>{_xe(name)}</name>")

            # Nội dung chính
            raw_content = r.get("raw_content") or r.get("text") or ""
            if raw_content:
                lines.append(f"  <content>{_xe(raw_content)}</content>")

            # Relationships (thông tin liên kết đồ thị)
            relationships = r.get("relationships", [])
            valid_rels = [
                rel for rel in relationships if rel.get("related_id") is not None
            ]

            if valid_rels:
                lines.append("  <relationships>")
                for rel in valid_rels:
                    rel_type = rel.get("rel_type", "UNKNOWN")
                    rel_id = rel.get("related_id", "")
                    rel_text = (
                        rel.get("related_text", "") or rel.get("related_name", "") or ""
                    )
                    if len(rel_text) > 500:
                        rel_text = rel_text[:500] + "..."
                    lines.append(
                        f'    <rel type="{_xe(rel_type)}" id="{_xe(rel_id)}">'
                        f"{_xe(rel_text)}</rel>"
                    )
                lines.append("  </relationships>")

            lines.append("</source>")
            context_blocks.append("\n".join(lines))

        # Present low-score blocks first so the highest-score block is closest
        # to the user question when context is injected into generator messages.
        return "\n\n".join(reversed(context_blocks))

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
        Async entry point — chạy 4 nhánh search SONG SONG.

        Chiến lược mới: Keyword + Vector + Graph + ConsequenceFirst (nhánh 4)

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

            # ── Bước 2: Chạy SONG SONG 4 nhánh với Timeout Guard ────────────
            logging.info(
                f"[GraphRetrievalTool] 🚀 Bắt đầu parallel search với timeouts: "
                f"keyword={self.keyword_timeout}s, vector={self.vector_timeout}s, "
                f"graph={self.graph_timeout}s, consequence={self.consequence_timeout}s | "
                f"query='{query[:50]}' | "
                f"violation='{entities.get('violation', '')[:50]}' | "
                f"vehicle='{entities.get('vehicle_type', '')}'"
            )

            # Wrap mỗi search với timeout guard
            async def search_with_timeout(coro, timeout: float, branch_name: str):
                """Helper để wrap search với timeout và error handling."""
                try:
                    return await asyncio.wait_for(coro, timeout=timeout)
                except asyncio.TimeoutError:
                    logging.warning(
                        f"[{branch_name}] ⏱️ Timeout after {timeout}s - returning empty results"
                    )
                    return []
                except Exception as e:
                    logging.error(f"[{branch_name}] Exception: {e}")
                    return []

            # Tạo tasks với timeout guards (4 nhánh)
            keyword_task = search_with_timeout(
                self._search_keyword(query), self.keyword_timeout, "Keyword"
            )
            vector_task = search_with_timeout(
                self._search_vector(vector), self.vector_timeout, "Vector"
            )
            graph_task = search_with_timeout(
                self._search_graph(entities), self.graph_timeout, "Graph"
            )
            consequence_task = search_with_timeout(
                self._search_consequence_first(query, entities),
                self.consequence_timeout,
                "ConsequenceFirst",
            )

            keyword_results, vector_results, graph_results, consequence_results = (
                await asyncio.gather(
                    keyword_task,
                    vector_task,
                    graph_task,
                    consequence_task,  # 4th branch
                )
            )

            logging.info(
                f"[GraphRetrievalTool] ✅ Parallel search hoàn tất: "
                f"keyword={len(keyword_results)} | "
                f"vector={len(vector_results)} | "
                f"graph={len(graph_results)} | "
                f"consequence={len(consequence_results)}"
            )

            # ── Bước 3: Merge + Deduplicate + Rank với RRF ───────────────────────
            merged = self._merge_results(
                keyword_results,
                vector_results,
                graph_results,
                consequence_results,  # Pass 4th branch
            )

            # ── Bước 3.5: Apply Vehicle-Aware Boosting (Post-RRF) ────────────────
            merged = self._apply_vehicle_boost(merged, entities)

            if not merged:
                not_found_msg = (
                    "Không tìm thấy thông tin liên quan trong cơ sở dữ liệu đồ thị. "
                    "Câu hỏi có thể nằm ngoài phạm vi Nghị định 168/2024/NĐ-CP."
                )
                self._write_query_log(query, entities, "(KHÔNG TÌM THẤY KẾT QUẢ)")
                return not_found_msg

            # ── Bước 3.6: THRESHOLDING — kiểm tra chất lượng kết quả ─────
            # Nếu điểm cao nhất vẫn dưới ngưỡng → Graph "đầu hàng" và signal cho Web Search
            max_score = merged[0].get("_rrf_score", 0) if merged else 0

            if max_score < self.rrf_threshold:
                low_confidence_msg = (
                    f"⚠️ [LOW_CONFIDENCE_THRESHOLD] Kết quả từ đồ thị có độ tin cậy thấp "
                    f"(max_rrf_score={max_score:.4f} < threshold={self.rrf_threshold}). "
                    f"Dữ liệu có thể chưa cập nhật hoặc không đủ chi tiết. "
                    f"Nên chuyển sang tìm kiếm web để bổ sung."
                )
                logging.warning(
                    f"[GraphRetrievalTool] RRF threshold check failed: "
                    f"max_score={max_score:.4f} < {self.rrf_threshold}"
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
    keyword_timeout: float = 3.0,
    vector_timeout: float = 5.0,
    graph_timeout: float = 5.0,
    consequence_timeout: float = 3.0,  # NEW
    rrf_threshold: float = 0.016,
    vehicle_boost_enabled: bool = True,  # NEW
    vehicle_boost_multiplier: float = 1.3,  # NEW
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
        (Legacy parameter, không còn sử dụng với RRF).
    keyword_timeout : float
        Timeout (giây) cho Fulltext keyword search (mặc định: 3.0s).
    vector_timeout : float
        Timeout (giây) cho Vector semantic search (mặc định: 5.0s).
    graph_timeout : float
        Timeout (giây) cho Graph traversal (mặc định: 5.0s).
    consequence_timeout : float
        Timeout (giây) cho Consequence-first branch (mặc định: 3.0s).
    rrf_threshold : float
        RRF score threshold tối thiểu để chấp nhận kết quả (mặc định: 0.016).
        - 0.025: Strict (≥2 sources, top ranks)
        - 0.016: Balanced (≥1 source, top-1) — Recommended
        - 0.010: Lenient (accept most results)
    vehicle_boost_enabled : bool
        Enable vehicle-type aware score boosting (mặc định: True).
    vehicle_boost_multiplier : float
        Score multiplier cho kết quả khớp loại xe (mặc định: 1.3).

    Returns
    -------
    GraphRetrievalTool
        Tool sẵn sàng bind vào LangChain agent.

    Example
    -------
    >>> tool = make_graph_retrieval_tool(
    ...     driver, embed_model,
    ...     top_k=5,
    ...     keyword_timeout=3.0,
    ...     vector_timeout=5.0,
    ...     graph_timeout=5.0,
    ...     consequence_timeout=3.0,
    ...     rrf_threshold=0.016,
    ...     vehicle_boost_enabled=True,
    ...     vehicle_boost_multiplier=1.3
    ... )
    >>> agent = create_react_agent(llm, tools=[tool], checkpointer=checkpointer)
    """
    return GraphRetrievalTool(
        driver=driver,
        embed_model=embed_model,
        top_k=top_k,
        score_threshold=score_threshold,
        keyword_timeout=keyword_timeout,
        vector_timeout=vector_timeout,
        graph_timeout=graph_timeout,
        consequence_timeout=consequence_timeout,
        rrf_threshold=rrf_threshold,
        vehicle_boost_enabled=vehicle_boost_enabled,
        vehicle_boost_multiplier=vehicle_boost_multiplier,
    )
