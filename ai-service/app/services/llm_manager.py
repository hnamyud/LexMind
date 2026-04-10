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
from langchain_openai import ChatOpenAI

def connect_llm(service) -> None:
    """
    Khởi tạo tất cả LLM instances và gán lên service.

    Args:
        service: RAGService instance có các attributes:
                 _api_key, _llm_router_model,
                 _llm_generator_model_l1/l2/l3, _llm_reflector_model
    """
    if not service._api_key:
        logging.error("❌ Thiếu GOOGLE_API_KEY")
        return
    try:
        # ── Router LLM (nhẹ, phân loại nhanh) 
        # service._llm_router = ChatGoogleGenerativeAI(
        #     model=service._llm_router_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     timeout=25,
        #     max_retries=1,
        # )

        # # # ── Direct LLM (agent_direct — streaming thật sự) 
        # service._llm_direct = ChatGoogleGenerativeAI(
        #     model=service._llm_direct_model,
        #     google_api_key=service._google_api_key,
        #     temperature=1.0,
        #     streaming=True,
        #     timeout=60,
        #     max_retries=2,
        # )

        # # # ── Generator LLMs (Complexity Level 1/2/3) 
        # # Level 1 — Simple: có thể thinking rất ít hoặc không
        # service._llm_gen_l1 = ChatGoogleGenerativeAI(
        #     model=service._llm_generator_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     thinking_level="low",
        #     include_thoughts=False,
        #     streaming=True,
        # )
        # # # Level 2 — Medium: thinking vừa phải
        # service._llm_gen_l2 = ChatGoogleGenerativeAI(
        #     model=service._llm_generator_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     thinking_level="medium",
        #     include_thoughts=True,
        #     streaming=True,
        # )
        # # # Level 3 — Complex: full thinking
        # service._llm_gen_l3 = ChatGoogleGenerativeAI(
        #     model=service._llm_generator_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     thinking_level="high",
        #     include_thoughts=True,
        #     streaming=True,
        # )

        # # # ── Reflector LLMs (budget = Generator / 4) ────────────────────
        # # Level 1: Reflector bị skip hoàn toàn — không cần instance
        # # Level 2:
        # service._llm_ref_l2 = ChatGoogleGenerativeAI(
        #     model=service._llm_reflector_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     # thinking_level="low",
        # )
        # # # Level 3:
        # service._llm_ref_l3 = ChatGoogleGenerativeAI(
        #     model=service._llm_reflector_model,
        #     google_api_key=service._google_api_key,
        #     temperature=0,
        #     thinking_level="low",
        # )

    # OpenAI Proxy (dùng cho test proxy model)

        service._llm_router = ChatOpenAI(
            model=service._llm_router_model,
            api_key=service._api_key,
            base_url=service._base_url,
            temperature=0,
            extra_body={
                "thinking": {"type": "disabled"}
            },
            max_tokens=1024,
        )

        # # ── Direct LLM (agent_direct — streaming thật sự) 
        service._llm_direct = ChatOpenAI(
            model=service._llm_direct_model,
            api_key=service._api_key,
            base_url=service._base_url,
            temperature=1.0,
            max_tokens=1024,
            streaming=True,
        )

        # # ── Generator LLMs (Complexity Level 1/2/3) 
        # # Level 1 — Simple: model nhẹ hơn (LLM_GENERATOR_L1)
        service._llm_gen_l1 = ChatOpenAI(
            model=service._llm_generator_model_l1,
            api_key=service._api_key,
            base_url=service._base_url,
            temperature=0,
            streaming=True,
        )
        # # Level 2 — Medium: thinking vừa phải (LLM_GENERATOR_L2)
        service._llm_gen_l2 = ChatOpenAI(
            model=service._llm_generator_model_l2,
            api_key=service._api_key,
            base_url=service._base_url,
            temperature=0,
            streaming=True,
        )
        # # Level 3 — Complex: full thinking (LLM_GENERATOR_L3)
        service._llm_gen_l3 = ChatOpenAI(
            model=service._llm_generator_model_l3,
            api_key=service._api_key,
            base_url=service._base_url,
            temperature=0,
            streaming=True,
        )

        # # ── Reflector LLMs (budget = Generator / 4) ────────────────────
        # # Level 1: Reflector bị skip hoàn toàn — không cần instance
        # # Level 2:
        service._llm_ref_l2 = ChatOpenAI(
            model=service._llm_reflector_model,
            api_key=service._api_key,
            base_url=service._base_url,
            max_tokens=512,
            temperature=0,
        )
        # # Level 3:
        service._llm_ref_l3 = ChatOpenAI(
            model=service._llm_reflector_model,
            api_key=service._api_key,
            base_url=service._base_url,
            max_tokens=1024,
            temperature=0,
        )

        # Alias _llm → _llm_gen_l1 (backward-compat cho agent_direct)
        service._llm = service._llm_gen_l1

        logging.info(
            "✅ Kết nối Gemini API thành công! "
            "(Router + Direct + Generator L1/L2/L3 + Reflector L2/L3)"
        )
    except Exception as e:
        logging.error(f"❌ Lỗi cấu hình Gemini API: {e}")
