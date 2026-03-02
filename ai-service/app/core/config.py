import os
from dotenv import load_dotenv, find_dotenv

load_dotenv()

class Settings:
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    EMBED_MODEL_ID: str = os.getenv("EMBED_MODEL_ID", "keepitreal/vietnamese-sbert")


settings = Settings()
