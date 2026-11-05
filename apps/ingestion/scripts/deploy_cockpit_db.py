import sys
import os
sys.path.append(os.getcwd())

from app.workers.bootstrap import get_pg_repo

def main():
    print("Initializing PostgresRepo...")
    pg = get_pg_repo()
    
    print("Applying default init SQL (includes ingestion_profiles)...")
    pg.apply_default_init_sql()
    
    print("Verifying table existence...")
    with pg._conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.ingestion_profiles')")
            res = cur.fetchone()
            if res and res[0] == 'ingestion_profiles':
                print("SUCCESS: Table 'ingestion_profiles' exists.")
            else:
                print("FAILURE: Table 'ingestion_profiles' NOT found.")

if __name__ == "__main__":
    main()
