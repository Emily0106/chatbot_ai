from typing import Generator, Optional
from app.core.config import settings
from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig

# Global instance for simplest local setup
# In production, you might want a proper dependency injection container or per-request pool
_repo: Optional[PostgresRepo] = None

def get_repo() -> Generator[PostgresRepo, None, None]:
    global _repo
    if _repo is None:
        cfg = PostgresRepoConfig(
            conninfo=str(settings.DATABASE_URL).replace("+asyncpg", ""),
            pool_min_size=1,
            pool_max_size=10,
            use_pool=True
        )
        _repo = PostgresRepo(cfg)
    yield _repo
