import os
from sqlalchemy import create_engine, text

def main():
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("No DB_URL")
        return
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    print(f"Connecting to {db_url}")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            stmt = text("SELECT 1")
            res = conn.execute(stmt)
            print(f"Select 1 result: {res.all()}")
            
            # Try insert (rollback later)
            stmt = text("INSERT INTO structured_rows (row_id, doc_category, data_content, citation) VALUES (:id, :cat, :data, :cit)")
            conn.execute(stmt, {"id": "test-uuid", "cat": "test", "data": "{}", "cit": "{}"})
            print("Insert success")
            conn.rollback()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
