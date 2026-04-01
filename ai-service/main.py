import logging
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.checkpoint import build_checkpointer, close_checkpointer
from app.services.rag_service import RAGService
from app.eval.migrations import run_eval_migrations
from app.eval.service import EvalService

from app.core.config import settings

# psycopg async pool is not compatible with ProactorEventLoop on Windows.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ---------------------------------------------------------------------------
# LangSmith Tracing Configuration
# Set env vars explicitly so LangChain/LangGraph auto-detect tracing
# ---------------------------------------------------------------------------
import os
if settings.LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ---------------------------------------------------------------------------
# Lifespan: thứ tự khởi tạo quan trọng
#   1. Tạo AsyncPostgresSaver (mở PostgreSQL pool, setup bảng checkpoint)
#   2. Tạo RAGService với checkpointer → initialize (Neo4j, Gemini, embed model)
#   3. Compile LangGraph với checkpointer bên trong initialize()
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ────────────────────────────────────────────────────────────
    logging.info("🚀 Khởi động ứng dụng...")

    # Bước 1: Khởi tạo PostgreSQL checkpointer (async, không block)
    logging.info("⏳ Đang khởi tạo AsyncPostgresSaver...")
    checkpointer = await build_checkpointer()

    # Bước 2: Tạo RAGService, truyền checkpointer vào
    logging.info("⏳ Đang khởi tạo RAG service...")
    svc = RAGService(checkpointer=checkpointer)
    await svc.initialize()  # Bên trong sẽ compile graph với checkpointer

    # Lưu vào app.state để các route có thể truy cập
    app.state.rag_service = svc
    app.state.checkpointer = checkpointer

    # Bước 3: Khởi tạo Eval pipeline
    logging.info("⏳ Đang khởi tạo Eval service...")
    pool = checkpointer.conn  # Tái dụng cùng AsyncConnectionPool
    await run_eval_migrations(pool)
    app.state.eval_service = EvalService(pool=pool, rag_service=svc)
    app.state.eval_pool = pool

    logging.info("✅ Toàn bộ service đã sẵn sàng!")

    yield  # ← Ứng dụng đang chạy

    # ── SHUTDOWN ───────────────────────────────────────────────────────────
    logging.info("🛑 Đang tắt ứng dụng...")
    await svc.close()                          # Đóng Neo4j connection
    await close_checkpointer(checkpointer)     # Đóng PostgreSQL pool


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="API Chatbot Luật Giao thông (RAG)",
    description="RAG API sử dụng Vector Search + Knowledge Graph (Nghị định 168/2024/NĐ-CP).",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.FASTAPI_URI, port=settings.FASTAPI_PORT, reload=True)
