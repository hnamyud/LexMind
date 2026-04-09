import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env từ root monorepo (thư mục cha của ai-service)
ROOT_DIR = Path(__file__).resolve().parents[3]  # ai-service/app/core/config.py -> root
load_dotenv(dotenv_path=ROOT_DIR / ".env")


class Settings:
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    LLM_ROUTER: str = os.getenv("LLM_ROUTER", "gemini-3.1-flash-lite-preview")
    LLM_DIRECT: str = os.getenv("LLM_DIRECT", "gemini-3.1-flash-lite-preview")
    LLM_GENERATOR: str = os.getenv("LLM_GENERATOR", "gemini-3-flash-preview")
    LLM_REFLECTOR: str = os.getenv("LLM_REFLECTOR", "gemini-3-flash-preview")
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")
    EMBED_MODEL_ID: str = os.getenv("EMBED_MODEL_ID")

    # PostgreSQL dùng cho LangGraph AsyncPostgresSaver
    # Format: postgresql+psycopg://user:password@host:port/dbname
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    # Redis Semantic Cache (cần Redis Stack cho RediSearch module)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    INTERNAL_SECRET: str = os.getenv("X-Internal-Secret")
    FASTAPI_URI: str = os.getenv("FASTAPI_URI", "127.0.0.1")
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8001"))

    # LangSmith Tracing
    LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "chatbot-law")
    LANGCHAIN_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")


settings = Settings()
