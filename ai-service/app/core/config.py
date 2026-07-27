import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env từ root monorepo (thư mục cha của ai-service)
ROOT_DIR = Path(__file__).resolve().parents[3]  # ai-service/app/core/config.py -> root
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=False)


class Settings:
    NEO4J_URI: str = os.getenv("NEO4J_URI", "")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    LOCAL_API_KEY: str = os.getenv("LOCAL_API_KEY", "")
    BASE_URL: str = os.getenv("BASE_URL", "")
    LLM_ROUTER: str = os.getenv("LLM_ROUTER", "")
    LLM_DIRECT: str = os.getenv("LLM_DIRECT", "")
    LLM_GENERATOR: str = os.getenv("LLM_GENERATOR", "gemini-3-flash-preview")
    # Per-level generator models — fallback to LLM_GENERATOR nếu không set
    LLM_GENERATOR_L1: str = os.getenv("LLM_GENERATOR_L1") or os.getenv("LLM_GENERATOR", "gemini-3-flash-preview")
    LLM_GENERATOR_L2: str = os.getenv("LLM_GENERATOR_L2") or os.getenv("LLM_GENERATOR", "gemini-3-flash-preview")
    LLM_GENERATOR_L3: str = os.getenv("LLM_GENERATOR_L3") or os.getenv("LLM_GENERATOR", "gemini-3-flash-preview")
    LLM_REFLECTOR: str = os.getenv("LLM_REFLECTOR", "gemini-3-flash-preview")
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")
    EMBED_MODEL_ID: str = os.getenv("EMBED_MODEL_ID", "huyydangg/DEk21_hcmute_embedding")
    # Revision 501d… is the repository revision that contains onnx/model.onnx.
    # Keep this overridable so a future verified ONNX revision can be deployed
    # without changing code.
    EMBED_MODEL_REVISION: str = os.getenv(
        "EMBED_MODEL_REVISION", "501df2abd66bfecf9f294c4d17741b0d9f3ebb7e"
    )
    EMBED_ONNX_PROVIDERS: str = os.getenv("EMBED_ONNX_PROVIDERS", "CPUExecutionProvider")
    EMBED_BATCH_SIZE: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))
    EMBED_MAX_LENGTH: int | None = int(os.getenv("EMBED_MAX_LENGTH")) if os.getenv("EMBED_MAX_LENGTH") else None
    EMBED_NORMALIZE: bool = os.getenv("EMBED_NORMALIZE", "false").lower() == "true"

    # PostgreSQL dùng cho LangGraph AsyncPostgresSaver
    # Format: postgresql+psycopg://user:password@host:port/dbname
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    # Redis Semantic Cache (cần Redis Stack cho RediSearch module)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    INTERNAL_SECRET: str = os.getenv("INTERNAL_SECRET")
    FASTAPI_URI: str = os.getenv("FASTAPI_URI", "127.0.0.1")
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8001"))
    ENABLE_EVAL_BOOT: bool = os.getenv("ENABLE_EVAL_BOOT", "true").lower() == "true"

    # LangSmith Tracing
    LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "chatbot-law")
    LANGCHAIN_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")


settings = Settings()
