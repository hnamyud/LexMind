import logging
import json
import yaml
from pathlib import Path
from typing import List, Optional

import neo4j
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator
from langchain_core.messages import HumanMessage as LCHumanMessage

from app.core.config import settings
from app.nodes.base import _extract_ai_text
from app.eval.service import EvalService

router = APIRouter()

api_key_header = APIKeyHeader(name="INTERNAL-SECRET", auto_error=True)

def verify_internal_secret(api_key: str = Depends(api_key_header)):
    if api_key != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="INTERNAL-SECRET không hợp lệ")
    return api_key


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    enable_web_search: bool = True
    enable_cache: bool = True


class GenerateTitleRequest(BaseModel):
    user_message: str
    bot_message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_service(request: Request):
    svc = request.app.state.rag_service
    if not svc:
        raise HTTPException(status_code=503, detail="RAG service chưa được khởi tạo.")
    return svc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", tags=["General"])
async def read_root():
    return {"message": "API Chatbot Luật Giao thông (RAG) v2.0 đang hoạt động!"}


@router.get("/health", tags=["General"])
async def health_check(request: Request):
    """Kiểm tra trạng thái API và các kết nối."""
    svc = request.app.state.rag_service
    return {
        "status": "healthy",
        "neo4j_connected": svc._driver is not None if svc else False,
        "gemini_configured": svc._llm is not None if svc else False,
        "embed_model_loaded": svc._embed_model is not None if svc else False,
        "cache_connected": svc._cache.is_connected if svc and svc._cache else False,
    }


@router.get("/debug", tags=["General"])
async def debug_info(request: Request):
    """Thông tin debug hệ thống."""
    import os
    svc = request.app.state.rag_service
    if not svc:
        return {"error": "RAG service not initialized"}
    return {
        "neo4j_uri": os.getenv("NEO4J_URI"),
        "neo4j_connected": svc._driver is not None,
        "gemini_configured": svc._llm is not None,
        "embed_model_id": svc._embed_model_id,
        "embed_model_loaded": svc._embed_model is not None,
        "embed_dimensions": (
            svc._embed_model.get_sentence_embedding_dimension()
            if svc._embed_model
            else None
        ),
        "cache_stats": svc._cache.get_stats() if svc._cache else None,
    }


# ---------------------------------------------------------------------------
# Cache Management
# ---------------------------------------------------------------------------

@router.delete("/cache", tags=["Cache"], dependencies=[Depends(verify_internal_secret)])
async def flush_cache(request: Request):
    """Xoá toàn bộ semantic cache (yêu cầu INTERNAL-SECRET)."""
    svc = _get_service(request)
    if not svc._cache or not svc._cache.is_connected:
        raise HTTPException(status_code=503, detail="Redis Semantic Cache chưa được kết nối.")
    success = await svc._cache.clear()
    if success:
        return {"status": "ok", "message": "Đã xóa toàn bộ semantic cache."}
    else:
        raise HTTPException(status_code=500, detail="Lỗi khi xóa cache.")


@router.get("/cache/stats", tags=["Cache"])
async def cache_stats(request: Request):
    """Lấy thống kê semantic cache."""
    svc = _get_service(request)
    if not svc._cache:
        return {"connected": False, "message": "Semantic Cache chưa được khởi tạo."}
    return svc._cache.get_stats()


@router.delete("/cache/invalidate/{law_tag}", tags=["Cache"], dependencies=[Depends(verify_internal_secret)])
async def invalidate_cache_by_tag(law_tag: str, request: Request):
    """Xóa cache entries theo law_tag (vd: nd_168_2024). Dùng khi update dữ liệu luật."""
    svc = _get_service(request)
    if not svc._cache or not svc._cache.is_connected:
        raise HTTPException(status_code=503, detail="Redis Semantic Cache chưa được kết nối.")
    count = await svc._cache.invalidate_by_tag(law_tag)
    return {"status": "ok", "tag": law_tag, "entries_removed": count}


# ---------------------------------------------------------------------------
# Graph endpoints
# ---------------------------------------------------------------------------

@router.get("/law-detail/{node_id}", tags=["Graph"])
async def get_law_detail(
    node_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Tra cứu chi tiết một node (điều luật, hành vi...) trong đồ thị Neo4j qua ID."""
    svc = _get_service(request)
    if not svc._driver:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu đồ thị chưa được kết nối.")
    
    # Truy vấn lấy properties của node và giới hạn số node liên quan để tránh bùng bộ nhớ
    query = """
    MATCH (start {id: $nodeId})-[:QUY_DINH_TAI|THUOC*0..2]->(p)
    WITH DISTINCT p
    LIMIT $limit
    RETURN collect(p) AS hierarchy
    """
    
    try:
        async with svc._driver.session(
            database=settings.NEO4J_DATABASE,
            default_access_mode=neo4j.READ_ACCESS,
        ) as session:
            result = await session.run(query, nodeId=node_id, limit=limit)
            records = await result.data()
            
        if not records or not records[0].get("hierarchy"):
            raise HTTPException(status_code=404, detail=f"Không tìm thấy node với id: {node_id}")
            
        # Loại bỏ embedding khỏi từng node trong hierarchy
        hierarchy = []
        for node in records[0]["hierarchy"]:
            props = dict(node)
            props.pop("embedding", None)
            hierarchy.append(props)

        return {
            "status": "success",
            "data": hierarchy
        }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Lỗi khi lấy chi tiết node {node_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn đồ thị: {str(e)}")


# ---------------------------------------------------------------------------
# Graph Demo endpoint
# ---------------------------------------------------------------------------

@router.get("/graph/demo", tags=["Graph"])
async def graph_demo(request: Request, id: str = "d6_k6"):
    """
    Trả về đồ thị con cho node gốc truyền vào qua query param `id`.

    Cypher sử dụng:
      MATCH path = (d:Entity {id: $node_id})-[*1..2]-(n)
      RETURN path
    """
    svc = _get_service(request)
    if not svc._driver:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu đồ thị chưa được kết nối.")

    query = """
    MATCH path = (d:Entity {id: $node_id})-[*1..2]-(n)
    RETURN path
    """

    type_alias_map = {
        "Article": "DieuKhoan",
        "Action": "HanhVi",
        "Vehicle": "PhuongTien",
        "Consequence": "MucPhat",
        "Penalty": "MucPhat",
        "AdditionalPenalty": "HinhPhatBoSung",
        "LegalDocument": "VanBanPhapLy",
        "Chapter": "Chuong",
        "Entity": "Entity",
    }

    def _clean_text(value: str) -> str:
        return " ".join(str(value).split())

    def _pick_node_label(props: dict, fallback_id: str) -> str:
        candidates = [
            props.get("text"),
            props.get("raw_text"),
            fallback_id,
        ]
        for candidate in candidates:
            if candidate:
                cleaned = _clean_text(candidate)
                if cleaned:
                    return cleaned[:120]
        return fallback_id

    try:
        async with svc._driver.session(
            database=settings.NEO4J_DATABASE,
            default_access_mode=neo4j.READ_ACCESS,
        ) as session:
            result = await session.run(query, node_id=id)
            # Keep raw Record objects so `path` stays a neo4j.graph.Path instance.
            records = [record async for record in result]

        if not records:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy path cho id: {id}")

        nodes_by_id: dict[str, dict] = {}
        edges_by_key: dict[tuple[str, str, str], dict] = {}

        for record in records:
            path = record.get("path")
            if not path:
                continue

            path_nodes = list(path.nodes)
            path_rels = list(path.relationships)

            for node in path_nodes:
                node_id = node.get("id")
                if not node_id:
                    continue

                props = dict(node)
                props.pop("embedding", None)

                labels = list(node.labels) if getattr(node, "labels", None) else []
                raw_type = props.get("label") or (labels[0] if labels else "Entity")
                node_type = type_alias_map.get(raw_type, raw_type)
                
                if node_id not in nodes_by_id:
                    nodes_by_id[node_id] = {
                        "id": node_id,
                        "label": _pick_node_label(props, node_id),
                        "type": node_type,
                        "description": (
                            _clean_text(
                                props.get("mo_ta")
                                or props.get("description")
                                or props.get("raw_text")
                                or ""
                            )
                        )[:280]
                    }

            # Relationship objects do not always expose full node objects consistently
            # across driver serialization modes, so map edges by path traversal order.
            for i, rel in enumerate(path_rels):
                source_node = path_nodes[i] if i < len(path_nodes) else None
                target_node = path_nodes[i + 1] if i + 1 < len(path_nodes) else None

                source = source_node.get("id") if source_node else None
                target = target_node.get("id") if target_node else None
                if not source or not target:
                    continue

                relation = rel.type
                edge_key = (source, target, relation)
                if edge_key not in edges_by_key:
                    edges_by_key[edge_key] = {
                        "source": source,
                        "target": target,
                        "relation": relation,
                    }

        nodes = list(nodes_by_id.values())
        edges = list(edges_by_key.values())

        if not nodes:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy node/path cho id: {id}")

        # Giữ bảng màu cho frontend, mở rộng thêm fallback Entity.
        type_meta = {
            "HanhVi": {"color": "#ef4444", "icon": "⚠️"},
            "PhuongTien": {"color": "#3b82f6", "icon": "🚗"},
            "MucPhat": {"color": "#f97316", "icon": "💰"},
            "HinhPhatBoSung": {"color": "#a855f7", "icon": "📋"},
            "VanBanPhapLy": {"color": "#10b981", "icon": "📜"},
            "Chuong": {"color": "#facc15", "icon": "📖"},
            "DieuKhoan": {"color": "#06b6d4", "icon": "§"},
            "Entity": {"color": "#64748b", "icon": "●"},
        }

        return {
            "status": "success",
            "seed_id": id,
            "query": "MATCH path = (d:Entity {id: $node_id})-[*1..2]-(n) RETURN path",
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "type_meta": type_meta,
            "nodes": nodes,
            "edges": edges,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Lỗi /graph/demo với id={id}: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn đồ thị demo: {str(e)}")


# ---------------------------------------------------------------------------
# Conversation Title Generation
# ---------------------------------------------------------------------------

@router.post("/conversations/generate-title", tags=["Conversations"], dependencies=[Depends(verify_internal_secret)])
async def generate_conversation_title(request: Request, body: GenerateTitleRequest):
    """
    Dùng LLM router (model nhẹ) để sinh tiêu đề ngắn gọn cho conversation
    từ cặp user_message + bot_message đầu tiên.
    Được gọi bất đồng bộ từ NestJS — không block luồng chat của user.
    """
    svc = _get_service(request)
    if not svc._llm_router:
        raise HTTPException(status_code=503, detail="LLM router chưa được khởi tạo.")

    prompt_path = Path(__file__).parent.parent / "prompts" / "title_generator.yaml"
    try:
        with open(prompt_path, encoding="utf-8") as f:
            prompt_template: str = yaml.safe_load(f)["template"]
    except Exception as e:
        logging.error(f"[generate-title] Không đọc được prompt: {e}")
        raise HTTPException(status_code=500, detail="Không đọc được prompt template.")

    prompt = prompt_template.format(
        user_message=body.user_message[:500],   # Giới hạn để tránh token quá dài
        bot_message=body.bot_message[:1000],
    )

    try:
        response = await svc._llm_router.ainvoke([LCHumanMessage(content=prompt)])
        # _extract_ai_text xử lý cả str lẫn list content (Gemini thinking)
        title = _extract_ai_text(response).strip()
        # Làm sạch: bỏ dấu ngoặc kép, truncate nếu quá dài
        title = title.strip('"\"\u201c\u201d').strip()
        title = title[:100] if len(title) > 100 else title
        logging.info(f"[generate-title] Title: {title!r}")
        return {"title": title}
    except Exception as e:
        logging.error(f"[generate-title] Lỗi gọi LLM: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi sinh tiêu đề: {str(e)}")


# ---------------------------------------------------------------------------
# RAG endpoints
# ---------------------------------------------------------------------------

@router.post("/ask/stream", tags=["RAG"], dependencies=[Depends(verify_internal_secret)])
async def ask_question_stream(request: Request, body: AskRequest):
    """
    Pipeline RAG với StreamingResponse (NDJSON):
    - `{"type": "thinking", "content": "..."}`: suy nghĩ nội bộ của LLM (reasoning)
    - `{"type": "thought",  "content": "..."}`: trạng thái tool (đang tra cứu...)
    - `{"type": "answer",   "content": "..."}`: nội dung trả lời (nhiều chunk)
    - `{"type": "metadata", "content": {...}}`: metadata bổ sung
    - `{"type": "done"}`: kết thúc
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    svc = _get_service(request)
    return StreamingResponse(
        svc.ask_stream(
            body.question,
            body.conversation_id,
            enable_web_search=body.enable_web_search,
            enable_cache=body.enable_cache,
        ),
        media_type="application/x-ndjson",
    )


@router.delete("/conversations/{conversation_id}/checkpoints", tags=["RAG"], dependencies=[Depends(verify_internal_secret)])
async def clear_conversation_checkpoint(conversation_id: str, request: Request):
    """
    Xóa toàn bộ checkpoint (bộ nhớ LangGraph) của một conversation_id.
    Thích hợp dùng cho tính năng Regenerate khi muốn loại bỏ lịch sử cũ bị lỗi.
    """
    svc = _get_service(request)
    if not svc._checkpointer:
        return {"status": "ok", "message": "Checkpointer không được thiết lập."}
    
    try:
        # Trong psycopg v3, biến truyền vào dùng %s
        # svc._checkpointer.conn chính là AsyncConnectionPool
        pool = svc._checkpointer.conn
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM checkpoints WHERE thread_id = %s;", (conversation_id,))
            await conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s;", (conversation_id,))
            await conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s;", (conversation_id,))
            
        return {"status": "success", "message": f"Đã xoá checkpoint cho conversation {conversation_id}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi khi xóa checkpoint: {str(e)}")


# ---------------------------------------------------------------------------
# Eval — Batch Evaluation + Manual Scoring
# ---------------------------------------------------------------------------

class RunBatchRequest(BaseModel):
    dataset: str = "nd_168_case.json"
    source_doc: Optional[str] = None   # Chỉ chấm câu thuộc 1 tài liệu nguồn cụ thể
    concurrency: int = 1               # Default 1 — an toàn nhất cho eval (tránh cache race)
    limit: Optional[int] = None        # None = chạy hết; N = chạy tối đa N câu
    random_sample: bool = True         # True = bốc ngẫu nhiên khi có limit; False = lấy từ đầu
    offset: int = 0                    # Bỏ qua N câu đầu (chỉ dùng khi random_sample=False)
    question_ids: Optional[List[str]] = None  # Nếu set → chỉ chạy các câu này (ignore limit/random)

    @field_validator("concurrency")
    @classmethod
    def concurrency_range(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("concurrency phải từ 1 đến 10")
        return v

    @field_validator("limit")
    @classmethod
    def limit_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("limit phải > 0")
        return v

    @field_validator("offset")
    @classmethod
    def offset_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("offset phải >= 0")
        return v



def _get_eval_service(request: Request):
    svc = getattr(request.app.state, "eval_service", None)
    if not svc:
        raise HTTPException(status_code=503, detail="Eval service chưa được khởi tạo.")
    return svc


@router.get(
    "/eval/datasets",
    tags=["Eval"],
    dependencies=[Depends(verify_internal_secret)],
    summary="Danh sách các bộ test/dataset hiện có",
)
async def eval_list_datasets(request: Request):
    """Trả về danh sách dataset kèm source_docs có thể filter."""
    dataset_dir = Path(__file__).parent.parent.parent / "test" / "dataset"
    if not dataset_dir.exists():
        return {"datasets": []}

    datasets = []
    for f in dataset_dir.glob("*.json"):
        source_docs = set()
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            for item in data if isinstance(data, list) else []:
                for src in item.get("source_docs", []) or []:
                    source_docs.add(src)
        except Exception:
            source_docs = set()

        datasets.append(
            {
                "name": f.name,
                "source_docs": sorted(source_docs),
            }
        )

    return {
        "datasets": datasets,
        "dataset_names": [d["name"] for d in datasets],
    }



@router.post(
    "/eval/run-batch",
    tags=["Eval"],
    dependencies=[Depends(verify_internal_secret)],
    summary="Kích hoạt batch evaluation qua dataset",
)
async def eval_run_batch(
    body: RunBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Chạy toàn bộ dataset qua LangGraph pipeline.
    - Trả về `session_id` ngay lập tức.
    - Batch chạy nền, polling tiến trình qua `GET /eval/results/{session_id}`.
    - Web search tự động bị tắt trong quá trình eval.
    """
    eval_svc = _get_eval_service(request)
    try:
        tracking = await eval_svc.run_batch(
            dataset_filename=body.dataset,
            concurrency=body.concurrency,
            limit=body.limit,
            random_sample=body.random_sample,
            offset=body.offset,
            question_ids=body.question_ids,
            source_doc=body.source_doc,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"[/eval/run-batch] {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi khởi động batch: {str(e)}")

    session_id = tracking["session_id"]

    return {
        "status": "started",
        "session_id": session_id,
        "dataset": tracking.get("dataset", body.dataset),
        "source_doc": tracking.get("source_doc"),
        "project_name": tracking.get("project_name", ""),
        "experiment_id": tracking.get("experiment_id", ""),
        "langsmith_url": tracking.get("langsmith_url", ""),
        "total": tracking.get("total"),
        "message": f"Batch đã bắt đầu. Xem real-time tại Langsmith URL (đính kèm) hoặc polling GET /eval/results/{session_id}",
    }


@router.get(
    "/eval/sessions",
    tags=["Eval"],
    dependencies=[Depends(verify_internal_secret)],
    summary="Danh sách các phiên eval gần đây",
)
async def eval_list_sessions(request: Request, limit: int = 20):
    eval_svc = _get_eval_service(request)
    sessions = await eval_svc.list_sessions(limit=limit)
    return {"sessions": sessions}


@router.get(
    "/eval/results/{session_id}",
    tags=["Eval"],
    dependencies=[Depends(verify_internal_secret)],
    summary="Kết quả từng câu trong session kèm retrieved_nodes",
)
async def eval_get_results(session_id: str, request: Request):
    """
    Trả về:
    - Thông tin session (status, progress)
    - List eval_runs kèm:
        - retrieved_nodes (thực tế từ RAG)
        - reference_nodes (kỳ vọng từ dataset)
        - retrieval_hit_rate (% khớp)
        - retrieval_missing / retrieval_extra
        - Tất cả scoring fields
    """
    eval_svc = _get_eval_service(request)

    session = await eval_svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session không tồn tại: {session_id}")

    runs = await eval_svc.get_results(session_id)
    return {
        "session": session,
        "runs": runs,
        "total": len(runs),
    }


@router.get(
    "/eval/stats/{session_id}",
    tags=["Eval"],
    dependencies=[Depends(verify_internal_secret)],
    summary="Thống kê tổng hợp cho một session",
)
async def eval_get_stats(session_id: str, request: Request):
    """
    Tính toán sẵn các chỉ số:
    - Avg score theo từng chiều
    - Avg retrieval hit rate
    - Phân bố issues
    - Breakdown theo difficulty
    """
    eval_svc = _get_eval_service(request)
    session = await eval_svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session không tồn tại: {session_id}")
    stats = await eval_svc.get_session_stats(session_id)
    return stats

