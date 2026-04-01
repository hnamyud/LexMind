"""
app/eval/service.py
────────────────────
EvalService — xử lý toàn bộ logic batch evaluation + manual scoring.

Luồng:
  1. run_batch()    → tạo eval_session, chạy LangGraph song song, lưu results
  2. get_results()  → truy vấn eval_runs theo session_id
  3. get_session()  → lấy thông tin phiên (status, progress)
  4. patch_score()  → cập nhật điểm chấm tay chi tiết

Cách extract retrieved_nodes:
  Tái sử dụng regex _RE_GRAPH_SOURCE của RAGService:
  "--- Nguồn <node_id> (score: X.XX | ...) ---"
  → lấy captured group(1) = node_id
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, AIMessage

# Regex tái sử dụng từ RAGService (không import class để tránh circular)
_RE_GRAPH_SOURCE = re.compile(
    r"---\s*Nguồn\s+(\S+)\s*\(score:\s*([\d.]+)\s*\|[^)]*\)\s*---"
)

_DATASET_DIR = Path(__file__).parent.parent.parent / "test" / "dataset"

VALID_ISSUES = {
    "wrong_amount",       # Mức phạt tiền/điểm sai
    "missing_article",    # Thiếu căn cứ Điều/Khoản
    "hallucination",      # Bot bịa ra điều không có trong luật
    "wrong_vehicle_type", # Nhầm loại xe
    "should_refuse",      # Phải từ chối nhưng không từ chối
    "incomplete",         # Đúng nhưng thiếu một phần
    "wrong_behavior",     # expected_behavior không khớp
    "over_retrieved",     # Lấy quá nhiều nodes không liên quan
}


def _extract_retrieved_nodes(context: str) -> list[str]:
    """
    Parse danh sách node IDs từ context text của graph retriever.
    Header format: "--- Nguồn d7_k7_c (score: 0.85 | hop: 0 | ...) ---"
    → return ["d7_k7_c", "d6_k9_b", ...]
    """
    if not context:
        return []
    seen = set()
    nodes = []
    for m in _RE_GRAPH_SOURCE.finditer(context):
        node_id = m.group(1)
        if node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
    return nodes


def _extract_ai_answer(final_messages: list) -> str:
    """Lấy nội dung text của AIMessage cuối cùng trong danh sách messages."""
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return " ".join(parts).strip()
    return ""


class EvalService:
    """
    Service cho pipeline đánh giá + chấm điểm tay.

    Parameters
    ----------
    pool : AsyncConnectionPool
        Shared connection pool (dùng chung với LangGraph checkpointer).
    rag_service : RAGService
        Instance đã khởi tạo đầy đủ (có _graph).
    """

    def __init__(self, pool, rag_service):
        self._pool = pool
        self._rag = rag_service

    @staticmethod
    def _resolve_langsmith_url(run_result: dict) -> str:
        """Resolve LangSmith URL from prebuilt field or raw results object."""
        if not isinstance(run_result, dict):
            return ""

        url = run_result.get("langsmith_url", "")
        if isinstance(url, str) and url.strip():
            return url.strip()

        raw_results = run_result.get("results")
        if raw_results is not None:
            for attr in ("url", "experiment_url", "session_url", "project_url", "results_url"):
                value = getattr(raw_results, attr, None)
                if isinstance(value, str) and value.strip().startswith("http"):
                    return value.strip()

        return ""

    @staticmethod
    def _normalize_behavior_score(value, db_type: str):
        """Normalize behavior score theo kiểu cột hiện có trong DB."""
        if value is None:
            return None

        normalized_type = (db_type or "").lower()
        if normalized_type in {"smallint", "integer", "bigint"}:
            try:
                return 2 if bool(value) else 0
            except Exception:
                return None

        return bool(value)

    # ──────────────────────────────────────────────────────────────────
    # 1. Batch Run
    # ──────────────────────────────────────────────────────────────────

    async def run_batch(
        self,
        dataset_filename: str = "nd_168_case.json",
        concurrency: int = 1,
        limit: Optional[int] = None,
        random_sample: bool = True,
        offset: int = 0,
        question_ids: Optional[list[str]] = None,
        source_doc: Optional[str] = None,
    ) -> dict:
        """
        Kích hoạt LangGraph chạy qua dataset (hoặc một phần).

        Parameters
        ----------
        limit : int | None
            Chạy tối đa N câu. None = chạy hết.
        random_sample : bool
            True  = bốc ngẫu nhiên N câu (khi limit được đặt) — mỗi lần test ra bộ câu khác nhau.
            False = lấy tuần tự từ đầu (kết hợp với offset để pagination).
        offset : int
            Bỏ qua N câu đầu (chỉ dùng khi random_sample=False).
        question_ids : list[str] | None
            Chỉ chạy các câu có id khớp (vd: ["q001", "q005"]).
            Khi đặt → bỏ qua limit/random/offset.

        Returns
        -------
        dict
            Metadata phiên eval để trả về API.
        """
        import random

        dataset_path = _DATASET_DIR / dataset_filename
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset không tìm thấy: {dataset_path}")

        with open(dataset_path, encoding="utf-8") as f:
            all_samples: list[dict] = json.load(f)

        if source_doc:
            all_samples = [
                s for s in all_samples
                if source_doc in (s.get("source_docs") or [])
            ]
            if not all_samples:
                raise ValueError(
                    f"Không có câu nào thuộc source_doc='{source_doc}' trong dataset '{dataset_filename}'"
                )

        # ── Filter theo question_ids (overrides limit/random/offset) ──────────────
        if question_ids:
            id_set = set(question_ids)
            samples = [s for s in all_samples if s.get("id") in id_set]
            if not samples:
                raise ValueError(f"Không tìm thấy câu nào khớp question_ids: {question_ids}")
            logging.info(
                f"[Eval] Filter by question_ids={question_ids} → {len(samples)} câu"
            )
        elif random_sample and limit is not None:
            # ── Random sampling: bốc ngẫu nhiên limit câu từ pool ──────────
            k = min(limit, len(all_samples))
            samples = random.sample(all_samples, k)
            logging.info(
                f"[Eval] Random sample {k}/{len(all_samples)} câu "
                f"(seed=random, không cố định)"
            )
        else:
            # ── Tuần tự: offset + limit ──────────────────────────────
            samples = all_samples[offset:]
            if limit is not None:
                samples = samples[:limit]

        if not samples:
            raise ValueError(
                f"Không có câu nào để chạy "
                f"(total={len(all_samples)}, offset={offset}, limit={limit})"
            )

        session_id = str(uuid.uuid4())
        experiment_prefix = f"lexmind-{session_id[:8]}"

        tracking = {
            "session_id": session_id,
            "dataset": dataset_filename,
            "source_doc": source_doc,
            "project_name": experiment_prefix,
            "experiment_id": "",
            "langsmith_url": "",
            "total": len(samples),
        }

        # Tạo session record
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO eval_sessions (
                    id, dataset, source_doc, project_name, experiment_id,
                    status, total, completed, langsmith_url
                )
                VALUES (%s, %s, %s, %s, %s, 'running', %s, 0, %s)
                """,
                (
                    session_id,
                    dataset_filename,
                    source_doc,
                    experiment_prefix,
                    "",
                    len(samples),
                    "",
                ),
            )

        logging.info(
            f"[Eval] LangSmith Batch START — session={session_id}, "
            f"dataset={dataset_filename}, source_doc={source_doc}, "
            f"total={len(samples)}, random_sample={random_sample}, concurrency={concurrency}"
        )

        # Lấy danh sách question_ids đã sample để truyền xuống task
        sampled_ids = [s.get("id") for s in samples if s.get("id")]

        asyncio.create_task(
            self._run_langsmith_eval_task(
                session_id=session_id,
                dataset_filename=dataset_filename,
                experiment_prefix=experiment_prefix,
                concurrency=concurrency,
                # Truyền IDs đã sample sẵn — task không cần tính lại offset/limit
                question_ids=sampled_ids if sampled_ids else question_ids,
                source_doc=source_doc,
            )
        )

        return tracking

    async def _run_langsmith_eval_task(
        self,
        session_id: str,
        dataset_filename: str,
        experiment_prefix: str,
        concurrency: int,
        question_ids: Optional[list[str]],
        source_doc: Optional[str],
    ) -> None:
        """Chạy LangSmith evaluation trong thread riêng (blocking call).

        Nhận `question_ids` đã được resolved từ bước sampling — không cần
        tính lại offset/limit/random bên trong task.
        Sau khi xong, sync kết quả vào eval_runs (INSERT).
        """
        loop = asyncio.get_running_loop()
        run_result: dict = {}

        def _run():
            from app.eval.evaluation.run_eval import run_evaluation
            return run_evaluation(
                dataset_name=dataset_filename,
                experiment_prefix=experiment_prefix,
                # Truyền question_ids đã sample sẵn → run_eval chỉ chạy đúng các câu này
                question_ids=question_ids,
                source_doc=source_doc,
                max_concurrency=concurrency,
            )

        try:
            run_result = await loop.run_in_executor(None, _run)
            final_status = "done"
        except Exception as e:
            logging.exception(f"[Eval] LangSmith Error: {e}")
            final_status = "failed"

        # ── Sync kết quả LangSmith → eval_runs ────────────────────────────
        run_records: list[dict] = run_result.get("run_records", []) if isinstance(run_result, dict) else []
        if run_records:
            await self._persist_run_records(session_id, run_records)

        try:
            langsmith_url = self._resolve_langsmith_url(run_result)
            async with self._pool.connection() as conn:
                await conn.execute(
                    """
                    UPDATE eval_sessions
                    SET status = %s,
                        completed = CASE WHEN %s = 'done' THEN total ELSE completed END,
                        langsmith_url = COALESCE(NULLIF(%s, ''), langsmith_url)
                    WHERE id = %s
                    """,
                    (
                        final_status,
                        final_status,
                        langsmith_url,
                        session_id,
                    ),
                )
        except Exception as ex:
            logging.error(f"Failed to update status: {ex}")

    async def _persist_run_records(self, session_id: str, records: list[dict]) -> None:
        """
        INSERT tất cả LangSmith run records vào bảng eval_runs.

        Schema mới — mapping trực tiếp từ LangSmith evaluators:
          score_correctness  ← correctness evaluator       (BOOLEAN)
          score_groundedness ← groundedness evaluator      (BOOLEAN)
          score_behavior     ← behavior_compliance         (BOOLEAN)
          score_citation     ← citation_accuracy           (BOOLEAN)
          retrieval_hit_rate ← retrieval_node_match        (FLOAT 0.0–1.0)
        """
        if not records:
            return

        logging.info(
            f"[Eval] Syncing {len(records)} records → eval_runs (session={session_id[:8]})"
        )

        try:
            async with self._pool.connection() as conn:
                behavior_score_type = "boolean"
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT data_type
                        FROM information_schema.columns
                        WHERE table_name = 'eval_runs'
                          AND column_name = 'score_behavior'
                        LIMIT 1
                        """
                    )
                    row = await cur.fetchone()
                    if row and row[0]:
                        behavior_score_type = row[0]

                for rec in records:
                    run_id = str(uuid.uuid4())
                    score_behavior_value = self._normalize_behavior_score(
                        rec.get("score_behavior"),
                        behavior_score_type,
                    )
                    await conn.execute(
                        """
                        INSERT INTO eval_runs (
                            id, session_id, question_id, question,
                            ground_truth, reference_nodes, retrieved_nodes,
                            ai_answer, context_text,
                            question_type, expected_behavior,
                            score_correctness, score_groundedness,
                            score_behavior, score_citation,
                            retrieval_hit_rate, scored_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, NOW()
                        )
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            run_id,
                            session_id,
                            rec.get("question_id", ""),
                            rec.get("question", ""),
                            rec.get("ground_truth", ""),
                            json.dumps(rec.get("reference_nodes", []), ensure_ascii=False),
                            json.dumps(rec.get("retrieved_nodes", []), ensure_ascii=False),
                            rec.get("ai_answer", ""),
                            rec.get("context_text", ""),
                            rec.get("question_type", ""),
                            rec.get("expected_behavior", ""),
                            rec.get("score_correctness"),    # BOOLEAN
                            rec.get("score_groundedness"),   # BOOLEAN
                            score_behavior_value,
                            rec.get("score_citation"),       # BOOLEAN
                            rec.get("retrieval_hit_rate"),   # FLOAT
                        ),
                    )

            logging.info(
                f"[Eval] ✅ Synced {len(records)} run_records → eval_runs (session={session_id[:8]})"
            )
        except Exception as e:
            logging.error(f"[Eval] ❌ Failed to persist run_records: {e}")






    async def _run_samples(
        self, session_id: str, samples: list[dict], concurrency: int
    ) -> None:
        """Chạy song song với semaphore để giới hạn concurrency."""
        sem = asyncio.Semaphore(concurrency)
        completed = 0

        async def _run_one(sample: dict) -> None:
            nonlocal completed
            async with sem:
                run_id = str(uuid.uuid4())
                question = sample.get("question", "")
                logging.info(
                    f"[Eval] [{session_id[:8]}] Running q={sample.get('id')} — {question[:60]}"
                )
                try:
                    context, ai_answer = await self._invoke_graph(question)
                    retrieved_nodes = _extract_retrieved_nodes(context)
                except Exception as e:
                    logging.error(f"[Eval] Error on {sample.get('id')}: {e}")
                    context, ai_answer, retrieved_nodes = "", f"[ERROR] {e}", []

                async with self._pool.connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO eval_runs (
                            id, session_id, question_id, question, ground_truth,
                            reference_nodes, retrieved_nodes, ai_answer,
                            context_text, difficulty, question_type,
                            expected_behavior, tags
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s
                        )
                        """,
                        (
                            run_id, session_id,
                            sample.get("id"),
                            question,
                            sample.get("ground_truth", ""),
                            json.dumps(sample.get("reference_nodes", []), ensure_ascii=False),
                            json.dumps(retrieved_nodes, ensure_ascii=False),
                            ai_answer,
                            context,
                            sample.get("difficulty"),
                            sample.get("question_type"),
                            sample.get("expected_behavior"),
                            json.dumps(sample.get("tags", []), ensure_ascii=False),
                        ),
                    )
                    completed += 1
                    await conn.execute(
                        "UPDATE eval_sessions SET completed = %s WHERE id = %s",
                        (completed, session_id),
                    )

        tasks = [_run_one(s) for s in samples]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Đánh dấu xong (hoặc failed nếu tất cả lỗi)
        errors = [r for r in results if isinstance(r, Exception)]
        final_status = "failed" if len(errors) == len(samples) else "done"

        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE eval_sessions SET status = %s WHERE id = %s",
                (final_status, session_id),
            )

        logging.info(
            f"[Eval] Batch DONE — session={session_id}, "
            f"status={final_status}, errors={len(errors)}/{len(samples)}"
        )

    async def _invoke_graph(self, question: str) -> tuple[str, str]:
        """
        Invoke LangGraph trực tiếp (không stream), disable web search VÀ cache.
        Mỗi lần eval dùng thread_id uuid riêng để tránh state leak giữa các câu.
        Returns (context_text, ai_answer).
        """
        initial_state = {
            "messages": [HumanMessage(content=question)],
        }
        config = {
            "configurable": {
                "thread_id": f"eval_{uuid.uuid4().hex}",  # thread riêng, không tái sử dụng
                "enable_web_search": False,  # tắt web search khi eval
                "enable_cache": False,        # tắt semantic cache khi eval
            },
            "run_name": f"eval — {question[:40]}",
        }

        final_state = await self._rag._graph.ainvoke(initial_state, config=config)

        context = final_state.get("context", "")
        messages = final_state.get("messages", [])
        ai_answer = _extract_ai_answer(messages)

        return context, ai_answer

    # ──────────────────────────────────────────────────────────────────
    # 2. Query Results
    # ──────────────────────────────────────────────────────────────────

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Trả về thông tin phiên eval (status, progress)."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, dataset, source_doc, project_name, experiment_id,
                           created_at, status, total, completed, langsmith_url
                    FROM eval_sessions WHERE id = %s
                    """,
                    (session_id,),
                )
                row = await cur.fetchone()
        if not row:
            return None
        cols = [
            "id", "dataset", "source_doc", "project_name", "experiment_id",
            "created_at", "status", "total", "completed", "langsmith_url",
        ]
        session = dict(zip(cols, row))
        session["created_at"] = session["created_at"].isoformat() if session["created_at"] else None
        session["progress_pct"] = (
            round(session["completed"] / session["total"] * 100, 1)
            if session["total"] > 0 else 0
        )
        return session

    async def get_results(self, session_id: str) -> list[dict]:
        """
        Trả về danh sách eval_runs kèm scores từ LangSmith AI evaluators.
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        r.id, r.question_id, r.question, r.ground_truth,
                        r.reference_nodes, r.retrieved_nodes, r.ai_answer,
                        r.context_text, r.difficulty, r.question_type,
                        r.expected_behavior, r.tags, r.created_at,
                        r.score_correctness, r.score_groundedness,
                        r.score_behavior, r.score_citation,
                        r.retrieval_hit_rate, r.scored_at
                    FROM eval_runs r
                    WHERE r.session_id = %s
                    ORDER BY r.question_id ASC NULLS LAST, r.created_at ASC
                    """,
                    (session_id,),
                )
                rows = await cur.fetchall()
                col_names = [desc[0] for desc in cur.description]

        results = []
        for row in rows:
            run = dict(zip(col_names, row))
            # Serialize datetime
            for dt_field in ("created_at", "scored_at"):
                if run.get(dt_field):
                    run[dt_field] = run[dt_field].isoformat()

            # JSONB có thể là str hoặc dict/list tùy driver
            for json_field in ("reference_nodes", "retrieved_nodes", "tags"):
                val = run.get(json_field)
                if isinstance(val, str):
                    try:
                        run[json_field] = json.loads(val)
                    except Exception:
                        run[json_field] = []
                if val is None:
                    run[json_field] = []

            # retrieval_hit_rate: đã là float từ LangSmith, nhân 100 để hiển thị %
            hit_rate_raw = run.get("retrieval_hit_rate")
            run["retrieval_hit_rate_pct"] = (
                round(float(hit_rate_raw) * 100, 1) if hit_rate_raw is not None else None
            )

            # Thiếu/thừa nodes (thiếu u lại từ reference và retrieved)
            ref      = set(run.get("reference_nodes") or [])
            retrieved = set(run.get("retrieved_nodes") or [])
            run["retrieval_missing"] = sorted(ref - retrieved)
            run["retrieval_extra"]   = sorted(retrieved - ref)

            results.append(run)

        return results

    # ──────────────────────────────────────────────────────────────────
    # 4. Session list (cho admin dashboard)
    # ──────────────────────────────────────────────────────────────────

    async def list_sessions(self, limit: int = 20) -> list[dict]:
        """Trả về danh sách các phiên eval gần đây."""
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, dataset, source_doc, project_name, experiment_id,
                           created_at, status, total, completed, langsmith_url
                    FROM eval_sessions
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = await cur.fetchall()
                col_names = [desc[0] for desc in cur.description]

        sessions = []
        for row in rows:
            s = dict(zip(col_names, row))
            if s.get("created_at"):
                s["created_at"] = s["created_at"].isoformat()
            s["progress_pct"] = (
                round(s["completed"] / s["total"] * 100, 1)
                if s["total"] > 0 else 0
            )
            sessions.append(s)
        return sessions

    # ──────────────────────────────────────────────────────────────────
    # 5. Aggregate stats cho session
    # ──────────────────────────────────────────────────────────────────

    async def get_session_stats(self, session_id: str) -> dict:
        """
        Tính thống kê tổng hợp cho một session:
        - Tỉ lệ pass (True) cho từng boolean score
        - Avg retrieval hit rate
        """
        runs = await self.get_results(session_id)
        if not runs:
            return {"session_id": session_id, "total": 0}

        total = len(runs)
        scored = [r for r in runs if r.get("scored_at")]

        def pct_true(field: str) -> Optional[float]:
            """Tỉ lệ % các run có score=True (không tính None)."""
            vals = [r[field] for r in scored if r.get(field) is not None]
            if not vals:
                return None
            return round(sum(1 for v in vals if v) / len(vals) * 100, 1)

        hit_rates = [
            r["retrieval_hit_rate"] for r in runs
            if r.get("retrieval_hit_rate") is not None
        ]
        avg_hit_rate = round(sum(hit_rates) / len(hit_rates) * 100, 1) if hit_rates else None

        return {
            "session_id":             session_id,
            "total":                  total,
            "scored":                 len(scored),
            "pct_correctness":        pct_true("score_correctness"),   # % câu trả lời đúng pháp lý
            "pct_groundedness":       pct_true("score_groundedness"),  # % không hallucinate
            "pct_behavior":           pct_true("score_behavior"),      # % đúng expected_behavior
            "pct_citation":           pct_true("score_citation"),      # % trích dẫn điều khoản đúng
            "avg_retrieval_hit_rate": avg_hit_rate,                    # % node hit trung bình
        }
