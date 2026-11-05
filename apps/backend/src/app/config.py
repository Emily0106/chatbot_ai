from __future__ import annotations

from typing import Optional
import os
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

import sys

CI_MODE = os.getenv("CI_MODE", "false").lower() in ("true", "1", "yes")

# Determine APP_MODE default (offline if pytest)
_default_mode = "offline" if "pytest" in sys.modules else "prod"
APP_MODE = os.getenv("APP_MODE", _default_mode).lower()
IS_OFFLINE = APP_MODE == "offline"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "postgres" if (CI_MODE or IS_OFFLINE) else Field(...)
    POSTGRES_PASSWORD: str = "postgres" if (CI_MODE or IS_OFFLINE) else Field(...)
    POSTGRES_DB: str = "postgres" if (CI_MODE or IS_OFFLINE) else Field(...)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    
    # Env & CI Mode
    ENV_MODE: str = os.getenv("ENV_MODE", "dev")
    APP_MODE: str = APP_MODE
    CI_MODE: bool = CI_MODE
    ALLOW_DEFAULT_TENANT: bool = False # Security: Block null-scope access by default

    QDRANT_URL: Optional[str] = "http://qdrant:6333" if (CI_MODE or IS_OFFLINE) else Field(...)
    QDRANT_API_KEY: str = "" # Deprecated in favor of specific keys
    QDRANT_READONLY_API_KEY: str = ""
    QDRANT_WRITE_API_KEY: str = ""
    QDRANT_COLLECTION: str = "gov_knowledge"
    VECTOR_DIM: int = 768 # Centralized Vector Dimension (PR-A2)
    
    REDIS_URL: Optional[str] = "redis://redis:6379/0" if (CI_MODE or IS_OFFLINE) else Field(...)
    
    # DB_URL se duoc dung boi SQLAlchemy (co the truyen truc tiep hoac computed)
    DB_URL: Optional[str] = "postgresql://postgres:postgres@postgres:5432/postgres" if (CI_MODE or IS_OFFLINE) else Field(...)

    OPENAI_API_KEY: Optional[str] = "dummy" if (CI_MODE or IS_OFFLINE) else Field(...)
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_TIMEOUT: float = 60
    OPENAI_MAX_RETRIES: int = 2

    OPENAI_MODEL_NAME: str = "gpt-4o-mini"
    SQL_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-ada-002"
    OPENAI_EMBEDDING_DIMENSIONS: int = 1536
    
    # Gate G0: Lock Identity
    EMBEDDING_MODEL_ID: str = "pilot-embedding-v1"

    # Embedding config
    EMBEDDING_BACKEND: str = "local" # openai | local
    EMBED_MODEL_PATH: str = "./models/all-MiniLM-L6-v2" # e.g. /models/vietnamese-sbert
    EMBEDDING_DEVICE: str = "cuda" # cpu | cuda | mps

    TAVILY_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    
    API_PREFIX: str = "/api"

    # Hybrid/Eco Retrieval
    RETRIEVAL_MODE: str = "auto"  # auto | gov | eco
    RETRIEVAL_DEADLINE_MS: int = 1500

    RERANK_ENABLED: bool = False
    RERANK_DEVICE: str = "cuda" # cpu | cuda | mps
    RERANK_TIMEOUT_S: float = 0.35
    RERANK_TRY_ACQUIRE: bool = True
    RERANK_BREAKER_FAILS: int = 5
    RERANK_BREAKER_FAILS: int = 5
    RERANK_BREAKER_COOLDOWN_S: float = 60.0

    # SQL Core Feature Flags
    ENABLE_NEW_SQL_CORE: bool = True
    SQL_SHADOW_MODE: bool = False
    SQL_EXECUTE_ALLOWED_ROLES: str = "admin,report,officer,chairman"

    # Temp Flow (Dual Data Flow)
    ENABLE_TEMP_DOCS: bool = True
    TEMP_DOC_TTL: int = 3600 # 1 hour
    ENABLE_TEMP_DOCS: bool = True
    TEMP_DOC_TTL: int = 3600 # 1 hour
    INGESTION_BASE_URL: str = "http://ingestion:8000" # Internal Docker URL
    INGEST_INTERNAL_TOKEN: str = ""
    OPS_CONSOLE_ENABLED: bool = False
    OPS_ADMIN_KEY: str = ""
    OPS_INGESTION_BASE_URL: str = ""
    OPS_HTTP_TIMEOUT_S: float = 12.0

    # Router Config (PR4)
    ENABLE_FAST_LANE: bool = False # Default off until stabilized
    FAST_TOP_K: int = 20
    FAST_PREFETCH_K: int = 40
    FAST_SKIP_RERANK: bool = True

    # Streaming Config (PR5)
    ENABLE_STREAMING_CHAT: bool = False # Default off
    STREAM_HEARTBEAT_S: int = 15
    STREAM_HEARTBEAT_S: int = 15
    STREAM_TIMEOUT_S: int = 60

    # Rate Limiting (PR6)
    ENABLE_RATE_LIMITING: bool = True
    RATE_LIMIT_RPS: float = 2.0
    RATE_LIMIT_BURST: int = 6
    MAX_INFLIGHT_PER_TENANT: int = 8
    MAX_STREAMS_PER_TENANT: int = 3
    RATE_LIMIT_REDIS_PREFIX: str = "govai:rl"
    RATE_LIMIT_REDIS_TIMEOUT_S: float = 0.2

    def runtime_validate(self) -> None:
        """
        Fail-closed runtime validation for staging/prod deployments.
        Ensures the app cannot start with insecure configurations.
        
        Raises:
            RuntimeError: If configuration is invalid for the current ENV_MODE
        """
        env = self.ENV_MODE.lower()
        
        # 1. ENV_MODE enforcement: prevent CI_MODE in staging/prod (MUST check before CI bypass)
        if env in ["staging", "prod"] and self.CI_MODE:
            raise RuntimeError(
                f"FATAL: CI_MODE cannot be enabled in {env.upper()} environment. "
                "Set CI_MODE=false or ENV_MODE=dev/ci."
            )
        
        # Skip remaining validation in CI mode (tests may use dummy values)
        if self.CI_MODE:
            return
        
        # 2. API Keys validation for staging/prod
        if env in ["staging", "prod"]:
            # Check if API_KEYS_JSON or similar exists
            # Since we don't have API_KEYS_JSON field, check if we're using dev defaults
            # The auth system uses require_auth dependency which reads from config
            # For now, we'll add a check that can be extended
            api_keys_json = os.getenv("API_KEYS_JSON", "")
            if not api_keys_json:
                raise RuntimeError(
                    f"FATAL: API_KEYS_JSON must be set in {env.upper()} environment. "
                    "Cannot use default dev keys in production."
                )
        
        # 3. Default tenant policy
        if env in ["staging", "prod"] and self.ALLOW_DEFAULT_TENANT:
            # Allow override with explicit migration flag
            migration_mode = os.getenv("MIGRATION_MODE", "false").lower() in ("true", "1", "yes")
            if not migration_mode:
                raise RuntimeError(
                    f"FATAL: ALLOW_DEFAULT_TENANT cannot be enabled in {env.upper()} environment. "
                    "Set ALLOW_DEFAULT_TENANT=false or enable MIGRATION_MODE=true temporarily."
                )
        
        # 4. Required secrets validation
        if env in ["staging", "prod"]:
            missing = []
            invalid = []
            
            # Database
            if not self.DB_URL:
                missing.append("DB_URL")
            elif self.DB_URL.startswith("postgresql://postgres:postgres@"):
                invalid.append("DB_URL uses default postgres credentials")
            
            # Vector DB - allow qdrant:6333 (valid for Docker Compose)
            if not self.QDRANT_URL:
                missing.append("QDRANT_URL")
            
            # Redis - allow redis:6379 (valid for Docker Compose)
            if not self.REDIS_URL:
                missing.append("REDIS_URL")
            
            # OpenAI (if using OpenAI backend)
            if self.EMBEDDING_BACKEND == "openai" or env == "prod":
                if not self.OPENAI_API_KEY:
                    missing.append("OPENAI_API_KEY")
                elif self.OPENAI_API_KEY == "dummy":
                    invalid.append("OPENAI_API_KEY uses dummy value")

            if missing or invalid:
                details = [f"  - missing: {m}" for m in missing]
                details.extend(f"  - invalid: {v}" for v in invalid)
                raise RuntimeError(
                    f"FATAL: Missing or invalid configuration for {env.upper()} environment:\n" +
                    "\n".join(details) +
                    "\n\nPlease set all required environment variables and remove insecure defaults."
                )


try:
    settings = Settings()
except ValidationError as e:
    # Check if DB_URL is missing
    # We can inspect e.errors() but a generic message for Prod is also fine if we know DB_URL is critical.
    # But settings might fail for other reasons.
    # Let's see if we can detect the specific field.
    error_str = str(e)
    if "DB_URL" in error_str:
        print("\n\033[91mFATAL CONFIG ERROR: Missing DB_URL in environment.\033[0m")
        print("For ENV_MODE=prod, you MUST set DB_URL in .env.prod or environment variables.")
        print("Example: DB_URL=postgresql+asyncpg://user:pass@host:5432/dbname\n")
        sys.exit(1)
    raise e
