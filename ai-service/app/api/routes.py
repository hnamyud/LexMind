import logging

import neo4j
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from app.core.config import settings

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
    }


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
