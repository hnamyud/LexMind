import logging
import yaml
from pathlib import Path

import neo4j
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from langchain_core.messages import HumanMessage as LCHumanMessage

from app.core.config import settings
from app.services.rag_service import _extract_ai_text

router = APIRouter()

api_key_header = APIKeyHeader(name="X-Internal-Secret", auto_error=True)

def verify_internal_secret(api_key: str = Depends(api_key_header)):
    if api_key != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="X-Internal-Secret không hợp lệ")
    return api_key


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


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
    """Xoá toàn bộ semantic cache (yêu cầu X-Internal-Secret)."""
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
async def get_law_detail(node_id: str, request: Request):
    """Tra cứu chi tiết một node (điều luật, hành vi...) trong đồ thị Neo4j qua ID."""
    svc = _get_service(request)
    if not svc._driver:
        raise HTTPException(status_code=503, detail="Cơ sở dữ liệu đồ thị chưa được kết nối.")
    
    # Truy vấn lấy properties của node, labels và các node liên quan (1-hop)
    query = """
    MATCH (start {id: $nodeId})-[:QUY_DINH_TAI|THUOC*0..]->(p)
    RETURN collect(p) AS hierarchy
    """
    
    try:
        async with svc._driver.session(
            database="neo4j",
            default_access_mode=neo4j.READ_ACCESS,
        ) as session:
            result = await session.run(query, nodeId=node_id)
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
        svc.ask_stream(body.question, body.conversation_id),
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
