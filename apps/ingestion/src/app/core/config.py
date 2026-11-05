# apps/ingestion/src/app/core/config.py
import os

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

class GovConfig:
    # Router
    INGEST_LANE = os.getenv("INGEST_LANE", "auto")  # auto|fast|heavy

    # Safety limits
    MAX_PAGE_COUNT = _env_int("MAX_PAGE_COUNT", 200)
    MAX_FILE_SIZE_MB = _env_int("MAX_FILE_SIZE_MB", 50)

    # Sniffer thresholds (tune dần)
    SNIFF_MIN_CHARS_HAS_TEXT = _env_int("SNIFF_MIN_CHARS_HAS_TEXT", 50)
    FAST_LANE_MAX_PAGES = _env_int("FAST_LANE_MAX_PAGES", 20)
    FAST_LANE_MIN_DENSITY = _env_int("FAST_LANE_MIN_DENSITY", 200)

    # Debug
    SNIFF_SAMPLE_PAGES = _env_int("SNIFF_SAMPLE_PAGES", 2)
    SNIFF_TIME_BUDGET_SEC = _env_float("SNIFF_TIME_BUDGET_SEC", 0.2)

class Settings:
    PROJECT_NAME = "Ingestion Service"
    API_V1_STR = "/api/v1"
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
    QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
    QDRANT_API_KEY = (
        os.getenv("QDRANT_API_KEY")
        or os.getenv("QDRANT_WRITE_API_KEY")
        or os.getenv("QDRANT_READONLY_API_KEY")
    )
    QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv("QDRANT_COLLECTION_NAME", "ingestion_chunks")
    QDRANT_COLLECTION_NAME = QDRANT_COLLECTION
    VECTOR_SIZE = _env_int("VECTOR_SIZE", 768)
    EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "pilot-embedding-v1")
    INGEST_INTERNAL_TOKEN = os.getenv("INGEST_INTERNAL_TOKEN", "")

settings = Settings()
