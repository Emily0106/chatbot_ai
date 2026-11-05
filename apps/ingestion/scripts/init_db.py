from app.preproc.stores.postgres_repo import PostgresRepo, PostgresRepoConfig
from app.core.config import settings

def main():
    print("Initializing DB...")
    db_url = settings.DATABASE_URL
    if not db_url:
        print("Error: DATABASE_URL not set")
        return

    repo = PostgresRepo(PostgresRepoConfig(conninfo=db_url))
    repo.apply_default_init_sql()
    print("DB initialized successfully.")

if __name__ == "__main__":
    main()
