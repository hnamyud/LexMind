import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


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
# RAG endpoints
# ---------------------------------------------------------------------------

@router.post("/ask", tags=["RAG"])
async def ask_question(request: Request, body: AskRequest):
    """
    Pipeline RAG chính (non-streaming):
    1. Query Transformation  2. Embedding  3. Hybrid Neo4j Search  4. Answer Synthesis
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    svc = _get_service(request)
    try:
        return await svc.ask(body.question)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Lỗi tại /ask: {e}")
        raise HTTPException(status_code=500, detail="Đã có lỗi xảy ra ở phía server.")


@router.post("/ask/stream", tags=["RAG"])
async def ask_question_stream(request: Request, body: AskRequest):
    """
    Pipeline RAG với StreamingResponse (NDJSON):
    - `{"type": "thought", "content": "..."}`: trạng thái từng bước
    - `{"type": "answer",  "content": "..."}`: nội dung trả lời (nhiều chunk)
    - `{"type": "done"}`: kết thúc
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống.")
    svc = _get_service(request)
    return StreamingResponse(
        svc.ask_stream(body.question, body.conversation_id),
        media_type="application/x-ndjson",
    )


# ---------------------------------------------------------------------------
# Debug / Test endpoints
# ---------------------------------------------------------------------------

@router.post("/test/rewrite", tags=["Debug"])
async def test_rewrite(request: Request, body: AskRequest):
    """Test query transformation: xem Gemini rewrite câu hỏi thành gì."""
    svc = _get_service(request)
    rewritten = await svc.rewrite_legal_query(body.question)
    return {"original": body.question, "rewritten": rewritten}


@router.post("/test/search", tags=["Debug"])
async def test_search(request: Request, body: AskRequest):
    """Test vector search: xem Neo4j trả về node nào (không sinh câu trả lời)."""
    svc = _get_service(request)
    legal_query = await svc.rewrite_legal_query(body.question)
    records, _ = await svc.hybrid_query(legal_query)
    return {
        "original": body.question,
        "rewritten_query": legal_query,
        "records_found": len(records),
        "records": records,
    }
