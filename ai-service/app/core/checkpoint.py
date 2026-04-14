"""
app/core/checkpoint.py
─────────────────────
Quản lý AsyncPostgresSaver (LangGraph) dùng async PostgreSQL connection pool.

Tại sao dùng AsyncPostgresSaver?
- Không block event-loop khi đọc/ghi checkpoint → các request khác vẫn xử lý song song.
- Một pool kết nối dùng chung cho toàn bộ vòng đời ứng dụng (tạo 1 lần, tắt khi shutdown).

Luồng sử dụng (trong FastAPI lifespan):
    checkpointer = await build_checkpointer(settings.DATABASE_URL)
    app.state.checkpointer = checkpointer
    yield
    await checkpointer.conn.close()   # đóng pool khi tắt server
"""

import logging
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings


async def build_checkpointer() -> AsyncPostgresSaver:
    """
    Tạo async connection pool → khởi tạo AsyncPostgresSaver → tạo bảng nếu chưa có.

    Returns
    -------
    AsyncPostgresSaver
        Checkpointer sẵn sàng dùng với graph.compile(checkpointer=...).
    """
    # LangGraph AsyncPostgresSaver dùng psycopg (v3) trực tiếp.
    # - Strip postgresql+psycopg:// → postgresql://
    # - Bỏ ?pgbouncer=true&connection_limit=1 vì psycopg3 không nhận params đó
    conninfo = settings.DATABASE_URL \
        .replace("postgresql+psycopg://", "postgresql://") \
        .split("?")[0]



    logging.info("⏳ Đang mở async PostgreSQL connection pool...")
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        max_size=10,          # tối đa 10 kết nối đồng thời
        kwargs={"autocommit": True},  # AsyncPostgresSaver yêu cầu autocommit=True
        open=False,           # chưa mở ngay, sẽ await pool.open() bên dưới
    )
    await pool.open()
    logging.info("✅ PostgreSQL connection pool đã mở!")

    checkpointer = AsyncPostgresSaver(pool)

    # Tạo các bảng checkpoint nếu chưa tồn tại (chỉ cần chạy 1 lần)
    await checkpointer.setup()
    logging.info("✅ AsyncPostgresSaver đã sẵn sàng! (bảng checkpoint đã được khởi tạo)")

    return checkpointer


async def close_checkpointer(checkpointer: AsyncPostgresSaver) -> None:
    """Đóng connection pool khi FastAPI shutdown."""
    try:
        await checkpointer.conn.close()
        logging.info("✅ PostgreSQL connection pool đã đóng.")
    except Exception as e:
        logging.warning(f"⚠️ Lỗi khi đóng PostgreSQL pool: {e}")
