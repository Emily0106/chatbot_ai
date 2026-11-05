import sys
sys.path.append("apps/ingestion/src")
sys.path.append("libs/core_shared")

from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.core.config import settings

def main():
    db_url = "postgresql://test:test@postgres:5432/test" # Force sync URL
    print(f"Initializing DB at {db_url}...")
    repo = PostgresRepo(PostgresRepoConfig(conninfo=db_url))
    repo.apply_default_init_sql()
    print("Schema initialized.")

if __name__ == "__main__":
    main()
