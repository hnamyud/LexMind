import asyncio
import json
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from langsmith import Client
from langsmith import schemas as ls_schemas


def _load_env_files() -> None:
    """Load env vars từ ai-service/.env và monorepo root .env nếu có."""
    current = Path(__file__).resolve()
    candidates = [
        current.parents[2] / ".env",  # ai-service/.env
        current.parents[3] / ".env",  # monorepo root/.env
    ]
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)


_load_env_files()

try:
    # Support module execution: python -m test.evaluation.run_eval
    from .evaluator import (
        correctness,
        behavior_compliance,
        groundedness,
        citation_accuracy,
        retrieval_node_match,
    )
    from .target import lexmind_target
except ImportError:
    # Support direct script execution: python test/evaluation/run_eval.py
    from evaluator import (
        correctness,
        behavior_compliance,
        groundedness,
        citation_accuracy,
        retrieval_node_match,
    )
    from target import lexmind_target


def _assert_service_reachable(service_url: str) -> None:
    parsed = urlparse(service_url)
    host = parsed.hostname or "localhost"
    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80

    try:
        with socket.create_connection((host, port), timeout=3):
            return
    except OSError as exc:
        raise RuntimeError(
            f"AI service is unreachable at {service_url}. "
            f"Please start ai-service before running evaluation."
        ) from exc


client = Client()


def _load_local_dataset(
    dataset_filename: str,
    max_examples: int | None = None,
    source_doc: str | None = None,
    question_ids: list[str] | None = None,
    offset: int = 0,
) -> list[dict]:
    # Prefer canonical dataset folder used by EvalService, fallback for legacy layouts.
    candidates = [
        Path(__file__).resolve().parents[3] / "test" / "dataset" / dataset_filename,
        Path(__file__).resolve().parents[1] / "dataset" / dataset_filename,
    ]
    dataset_path = next((p for p in candidates if p.exists()), None)
    if dataset_path is None:
        tried = " | ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            f"Dataset {dataset_filename} không tồn tại. Checked: {tried}"
        )

    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)

    if source_doc:
        data = [item for item in data if source_doc in (item.get("source_docs") or [])]

    if question_ids:
        question_id_set = set(question_ids)
        data = [item for item in data if item.get("id") in question_id_set]

    if offset > 0:
        data = data[offset:]

    if max_examples is not None and max_examples > 0:
        data = data[:max_examples]

    formatted_data = []
    for item in data:
        inputs = {
            "id": item.get("id", ""),
            "question": item.get("question", ""),
            "question_type": item.get("question_type", ""),
            "expected_behavior": item.get("expected_behavior", ""),
            "source_docs": item.get("source_docs", []),
        }
        reference_outputs = {
            "ground_truth": item.get("ground_truth", ""),
            "reference_nodes": item.get("reference_nodes", []),
            "source_docs": item.get("source_docs", []),
        }
        formatted_data.append({"inputs": inputs, "reference_outputs": reference_outputs})

    return formatted_data


def _build_langsmith_compare_url(results) -> str:
    """Build LangSmith compare URL when experiment/session identifiers are available."""
    tenant_id = getattr(results, "_tenant_id", None)
    dataset_id = getattr(results, "_dataset_id", None)
    experiment = getattr(results, "experiment_name", None)

    if not (tenant_id and dataset_id and experiment):
        return ""

    return (
        f"https://smith.langchain.com/o/{tenant_id}/datasets/{dataset_id}/compare"
        f"?selectedSessions={experiment}"
    )


def _create_langsmith_dataset_from_local(
    local_samples: list[dict],
    dataset_name: str,
    experiment_prefix: str,
) -> str:
    """
    Upload local JSON samples thành dataset tạm trên LangSmith và trả về dataset_id.
    """
    unique_suffix = uuid.uuid4().hex[:8]
    ls_dataset_name = f"{experiment_prefix}-{Path(dataset_name).stem}-{unique_suffix}"

    dataset = client.create_dataset(
        dataset_name=ls_dataset_name,
        description="Temporary dataset for API-triggered eval run",
        data_type=ls_schemas.DataType.kv,
        metadata={
            "source_dataset": dataset_name,
            "created_by": "eval_api",
        },
    )

    # LangSmith examples use outputs as reference outputs for evaluators.
    examples = [
        {
            "inputs": s.get("inputs", {}),
            "outputs": s.get("reference_outputs", {}),
            "metadata": {
                "question_id": (s.get("inputs") or {}).get("id"),
            },
        }
        for s in local_samples
    ]

    client.create_examples(dataset_id=dataset.id, examples=examples)
    return str(dataset.id)


def run_evaluation(
    dataset_name: str = "nd_168_case.json",
    experiment_prefix: str = "lexmind-eval",
    version: str = "v1.0",
    max_examples: int | None = None,
    source_doc: str | None = None,
    question_ids: list[str] | None = None,
    offset: int = 0,
    max_concurrency: int = 4,
):
    """
    Chạy evaluation từ dữ liệu JSON local sử dụng LangSmith.
    """
    try:
        from .target import AI_SERVICE_URL
    except ImportError:
        from target import AI_SERVICE_URL

    _assert_service_reachable(AI_SERVICE_URL)

    def sync_target(inputs: dict) -> dict:
        return asyncio.run(lexmind_target(inputs))

    data_source = _load_local_dataset(
        dataset_filename=dataset_name,
        max_examples=max_examples,
        source_doc=source_doc,
        question_ids=question_ids,
        offset=offset,
    )

    if not data_source:
        raise ValueError(
            f"Không có samples hợp lệ để chạy eval (dataset={dataset_name}, "
            f"source_doc={source_doc}, offset={offset}, max_examples={max_examples})."
        )

    dataset_id = _create_langsmith_dataset_from_local(
        local_samples=data_source,
        dataset_name=dataset_name,
        experiment_prefix=experiment_prefix,
    )

    results = client.evaluate(
        sync_target,
        data=dataset_id,
        evaluators=[
            correctness,          # inputs + outputs + reference_outputs → ground_truth
            behavior_compliance,  # inputs (expected_behavior) + outputs (verdict, answer)
            groundedness,         # outputs (context, answer)
            citation_accuracy,    # outputs (context, answer)
            retrieval_node_match, # outputs (retrieved_nodes) + reference_outputs (reference_nodes)
        ],
        experiment_prefix=experiment_prefix,
        metadata={
            "version": version,
            "model": "gemini-2.5-flash",
            "retrieval": "hybrid_4_branch_rrf",
            "cache": "redis_semantic_entity_filter",
        },
        max_concurrency=max_concurrency,
    )

    # In summary ra terminal
    df = results.to_pandas()
    cols = {
        "correctness":          "feedback.correctness",
        "behavior_compliance":  "feedback.behavior_compliance",
        "groundedness":         "feedback.groundedness",
        "citation_accuracy":    "feedback.citation_accuracy",
        "retrieval_node_match": "feedback.retrieval_node_match",
    }

    print("\n=== Evaluation Results ===")
    for label, col in cols.items():
        if col in df.columns:
            print(f"{label:<24} {df[col].mean():.1%}")
        else:
            print(f"{label:<24} N/A (column missing)")

    available = [c for c in cols.values() if c in df.columns]
    if available:
        overall = df[available].mean().mean()
        print(f"{'Overall':<24} {overall:.1%}")

    # Parse DataFrame → records để service sync vào eval_runs
    run_records = _extract_run_records(df, data_source)

    return {
        "results": results,
        "sample_count": len(data_source),
        "experiment_id": getattr(results, "experiment_name", ""),
        "project_name": experiment_prefix,
        "langsmith_url": _build_langsmith_compare_url(results),
        "run_records": run_records,   # ← list records sẵn sàng INSERT vào eval_runs
        "summary": {
            label: (float(df[col].mean()) if col in df.columns else None)
            for label, col in cols.items()
        },
    }


def _extract_run_records(df, data_source: list[dict]) -> list[dict]:
    """
    Parse LangSmith results DataFrame thành list dicts sẵn sàng INSERT vào eval_runs.

    LangSmith evaluator return types:
      - correctness        → bool  (True/False) → LangSmith lưu 1.0/0.0
      - groundedness       → bool  (True/False) → LangSmith lưu 1.0/0.0
      - behavior_compliance→ bool  (True/False) → LangSmith lưu 1.0/0.0
      - citation_accuracy  → bool  (True/False) → LangSmith lưu 1.0/0.0
      - retrieval_node_match→ float (0.0–1.0)   → tỉ lệ hit thực, giữ nguyên

    LangSmith DataFrame column conventions:
      inputs.*             — input fields từ dataset (question, id, ...)
      outputs.*            — output fields từ target fn (answer, context, retrieved_nodes, ...)
      reference_outputs.*  — reference fields (ground_truth, reference_nodes, ...)
      feedback.*           — evaluator scores
    """
    # Build lookup: question_id → sample metadata
    sample_by_id: dict[str, dict] = {}
    for s in data_source:
        inp = s.get("inputs") or {}
        qid = inp.get("id", "")
        ref = s.get("reference_outputs") or {}
        sample_by_id[qid] = {
            "question":          inp.get("question", ""),
            "question_type":     inp.get("question_type", ""),
            "expected_behavior": inp.get("expected_behavior", ""),
            "ground_truth":      ref.get("ground_truth", ""),
            "reference_nodes":   ref.get("reference_nodes", []),
        }

    records = []
    for _, row in df.iterrows():
        qid    = _col(row, "inputs.id") or ""
        sample = sample_by_id.get(qid, {})

        # ── Inputs / reference ──────────────────────────────────────────────
        question     = _col(row, "inputs.question")     or sample.get("question", "")
        ground_truth = _col(row, "reference_outputs.ground_truth") or sample.get("ground_truth", "")
        ref_nodes_raw = _col(row, "reference_outputs.reference_nodes")
        ref_nodes     = ref_nodes_raw if isinstance(ref_nodes_raw, list) else sample.get("reference_nodes", [])

        # ── Outputs từ target ───────────────────────────────────────────────
        answer          = _col(row, "outputs.answer")          or ""
        context         = _col(row, "outputs.context")         or ""
        ret_nodes_raw   = _col(row, "outputs.retrieved_nodes")
        retrieved_nodes = ret_nodes_raw if isinstance(ret_nodes_raw, list) else []

        # ── LangSmith feedback scores ───────────────────────────────────────
        # bool evaluators: LangSmith lưu True→1.0, False→0.0
        # → dùng _score_bool() để convert về Python bool (hoặc None nếu missing)
        score_correctness  = _score_bool(_col(row, "feedback.correctness"))
        score_groundedness = _score_bool(_col(row, "feedback.groundedness"))
        score_behavior     = _score_bool(_col(row, "feedback.behavior_compliance"))
        score_citation     = _score_bool(_col(row, "feedback.citation_accuracy"))

        # float evaluator: retrieval_node_match trả về float thực 0.0–1.0
        # → giữ nguyên precision, không ép về bool hay int
        retrieval_hit_rate = _score_float(_col(row, "feedback.retrieval_node_match"))

        records.append({
            "question_id":        qid,
            "question":           question,
            "ground_truth":       ground_truth,
            "reference_nodes":    ref_nodes,
            "retrieved_nodes":    retrieved_nodes,
            "ai_answer":          answer,
            "context_text":       context,
            "question_type":      sample.get("question_type",     _col(row, "inputs.question_type")     or ""),
            "expected_behavior":  sample.get("expected_behavior", _col(row, "inputs.expected_behavior") or ""),
            # Mapping 1:1 với schema DB mới
            "score_correctness":  score_correctness,   # BOOLEAN
            "score_groundedness": score_groundedness,  # BOOLEAN
            "score_behavior":     score_behavior,       # BOOLEAN
            "score_citation":     score_citation,       # BOOLEAN
            "retrieval_hit_rate": retrieval_hit_rate,   # FLOAT 0.0–1.0
        })

    return records


def _col(row, name: str):
    """Lấy giá trị cột từ DataFrame row — trả về None nếu không tồn tại hoặc NaN."""
    import math
    if name not in row.index:
        return None
    val = row[name]
    try:
        if isinstance(val, float) and math.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


def _score_bool(val) -> bool | None:
    """
    Chuyển LangSmith bool score về Python bool.

    LangSmith lưu bool evaluator results dưới dạng:
      - True  → 1.0  (float)
      - False → 0.0  (float)
      - Missing → NaN → None sau _col()
    """
    if val is None:
        return None
    try:
        return bool(float(val) >= 0.5)   # ≥0.5 → True, <0.5 → False
    except (TypeError, ValueError):
        return None


def _score_float(val) -> float | None:
    """
    Lấy float score thuần từ LangSmith (dùng cho retrieval_hit_rate).
    None nếu missing.
    """
    if val is None:
        return None
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    run_evaluation(max_examples=10)