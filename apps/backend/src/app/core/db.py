# apps/backend/src/app/core/db.py
from sqlalchemy.orm import DeclarativeBase
from app.core.db_sql import get_async_db, _Session as async_session_factory

class Base(DeclarativeBase):
    pass
