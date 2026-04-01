"""
app/eval/migrations.py
─────────────────────
Tạo các bảng PostgreSQL dùng cho eval pipeline.
Gọi 1 lần khi app startup, không block nếu bảng đã tồn tại.
"""

import logging


EVAL_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS eval_sessions (
    id          TEXT PRIMARY KEY,
    dataset     TEXT NOT NULL,
    source_doc  TEXT,
    project_name TEXT,
    experiment_id TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    status      TEXT DEFAULT 'running',
    total       INT  DEFAULT 0,
    completed   INT  DEFAULT 0,
    langsmith_url TEXT
);
"""

EVAL_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id                TEXT PRIMARY KEY,
    session_id        TEXT REFERENCES eval_sessions(id) ON DELETE CASCADE,
    question_id       TEXT,
    question          TEXT,
    ground_truth      TEXT,
    reference_nodes   JSONB,
    retrieved_nodes   JSONB DEFAULT '[]'::jsonb,
    ai_answer         TEXT,
    context_text      TEXT,
    difficulty        TEXT,
    question_type     TEXT,
    expected_behavior TEXT,
    tags              JSONB DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ DEFAULT NOW(),

    -- Manual scoring (detailed)
    score_retrieval   SMALLINT,      -- 0 = miss, 1 = partial, 2 = hit
    score_context     SMALLINT,      -- 0 = sai/nhiễu, 1 = có nhưng thiếu, 2 = đủ và chính xác
    score_answer      SMALLINT,      -- 0 = sai, 1 = partially correct, 2 = đúng hoàn toàn
    score_behavior    SMALLINT,      -- 0 = sai expected_behavior, 2 = đúng
    issues            JSONB DEFAULT '[]'::jsonb, -- ["wrong_amount", "hallucination", ...]
    note              TEXT,
    scored_at         TIMESTAMPTZ,
    scored_by         TEXT           -- admin username / label
);
"""

EVAL_RUNS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_eval_runs_session_id
    ON eval_runs (session_id);
"""


async def run_eval_migrations(pool) -> None:
    """
    Tạo bảng eval_sessions và eval_runs nếu chưa tồn tại.
    `pool` là AsyncConnectionPool từ psycopg_pool.
    """
    logging.info("⏳ [Eval] Đang chạy migrations...")
    try:
        async with pool.connection() as conn:
            await conn.execute(EVAL_SESSIONS_DDL)
            try:
                await conn.execute("ALTER TABLE eval_sessions ADD COLUMN langsmith_url TEXT;")
            except Exception:
                pass # Bỏ qua nếu cột đã tồn tại
            try:
                await conn.execute("ALTER TABLE eval_sessions ADD COLUMN source_doc TEXT;")
            except Exception:
                pass
            try:
                await conn.execute("ALTER TABLE eval_sessions ADD COLUMN project_name TEXT;")
            except Exception:
                pass
            try:
                await conn.execute("ALTER TABLE eval_sessions ADD COLUMN experiment_id TEXT;")
            except Exception:
                pass
            await conn.execute(EVAL_RUNS_DDL)
            await conn.execute(EVAL_RUNS_INDEX_DDL)
        logging.info("✅ [Eval] Migrations hoàn tất (bảng eval_sessions + eval_runs).")
    except Exception as e:
        logging.error(f"❌ [Eval] Migration failed: {e}")
        raise
