"""
services/llm_manager.py
───────────────────────
Khởi tạo và quản lý tất cả LLM instances cho RAG pipeline.

Hàm public:
  connect_llm(service) → None  (Option B: gán trực tiếp lên service instance)

LLM instances được tạo:
  Router   : _llm_router              (nhẹ, temperature=0, không thinking)
  Generator: _llm_gen_l1/l2/l3        (3 levels of thinking complexity)
  Reflector: _llm_ref_l2/l3           (2 levels — Level 1 bị skip hoàn toàn)
  Alias    : _llm = _llm_gen_l1       (backward compat)
"""

import logging

from langchain_google_genai import ChatGoogleGenerativeAI


def connect_llm(service) -> None:
    """
    Khởi tạo tất cả LLM instances và gán lên service.

    Args:
        service: RAGService instance có các attributes:
                 _api_key, _llm_router_model, _llm_generator_model, _llm_reflector_model
    """
    if not service._api_key:
        logging.error("❌ Thiếu GOOGLE_API_KEY")
        return
    try:
        # ── Router LLM (nhẹ, phân loại nhanh) ─────────────────────────
        # timeout=25 : fail fast nếu API chậm — tránh treo 70s+ (504 deadline exceeded)
        # max_retries=1: 1 retry với exponential backoff, rồi fallback use_tool
        # temperature=0: classification cần deterministic, không sáng tạo
        service._llm_router = ChatGoogleGenerativeAI(
            model=service._llm_router_model,
            google_api_key=service._api_key,
            temperature=0,
            timeout=25,
            max_retries=1,
        )

        # ── Direct LLM (agent_direct — streaming thật sự) ──────────────
        # streaming=True : giữ connection sống, tránh server-side 504 deadline exceeded
        #                  LangGraph tự phát on_chat_model_stream → frontend nhận token ngay
        # timeout=60     : conversational response không cần thinking nên 60s là đủ
        # temperature=1.0: Gemini 3.x+ recommend default=1.0 cho conversational quality;
        #                  lower values (0.7, 0) có thể gây degraded performance
        # max_retries=2  : 2 retries exponential backoff cho 504/503 transient errors
        service._llm_direct = ChatGoogleGenerativeAI(
            model=service._llm_direct_model,
            google_api_key=service._api_key,
            temperature=1.0,
            streaming=True,
            timeout=60,
            max_retries=2,
        )

        # ── Generator LLMs (Complexity Level 1/2/3) ────────────────────
        # Level 1 — Simple: có thể thinking rất ít hoặc không
        service._llm_gen_l1 = ChatGoogleGenerativeAI(
            model=service._llm_generator_model,
            google_api_key=service._api_key,
            temperature=0,
            thinking_level="low",
            include_thoughts=False,
            streaming=True,
        )
        # Level 2 — Medium: thinking vừa phải
        service._llm_gen_l2 = ChatGoogleGenerativeAI(
            model=service._llm_generator_model,
            google_api_key=service._api_key,
            temperature=0,
            thinking_level="medium",
            include_thoughts=True,
            streaming=True,
        )
        # Level 3 — Complex: full thinking
        service._llm_gen_l3 = ChatGoogleGenerativeAI(
            model=service._llm_generator_model,
            google_api_key=service._api_key,
            temperature=0,
            thinking_level="high",
            include_thoughts=True,
            streaming=True,
        )

        # ── Reflector LLMs (budget = Generator / 4) ────────────────────
        # Level 1: Reflector bị skip hoàn toàn — không cần instance
        # Level 2:
        service._llm_ref_l2 = ChatGoogleGenerativeAI(
            model=service._llm_reflector_model,
            google_api_key=service._api_key,
            temperature=0,
            thinking_level="low",
        )
        # Level 3:
        service._llm_ref_l3 = ChatGoogleGenerativeAI(
            model=service._llm_reflector_model,
            google_api_key=service._api_key,
            temperature=0,
            thinking_level="medium",
        )

        # Alias _llm → _llm_gen_l1 (backward-compat cho agent_direct)
        service._llm = service._llm_gen_l1

        logging.info(
            "✅ Kết nối Gemini API thành công! "
            "(Router + Direct + Generator L1/L2/L3 + Reflector L2/L3)"
        )
    except Exception as e:
        logging.error(f"❌ Lỗi cấu hình Gemini API: {e}")
