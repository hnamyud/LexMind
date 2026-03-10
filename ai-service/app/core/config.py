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
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")
    EMBED_MODEL_ID: str = os.getenv("EMBED_MODEL_ID")

    # PostgreSQL dùng cho LangGraph AsyncPostgresSaver
    # Format: postgresql+psycopg://user:password@host:port/dbname
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    INTERNAL_SECRET: str = os.getenv("X-Internal-Secret")
    FASTAPI_URI: str = os.getenv("FASTAPI_URI")
    FASTAPI_PORT: str = os.getenv("FASTAPI_PORT")


settings = Settings()
