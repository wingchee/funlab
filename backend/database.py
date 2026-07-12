import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/data/pindou.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def configure_sqlite_foreign_keys(target_engine):
    if target_engine.dialect.name != "sqlite":
        return target_engine
    if not event.contains(target_engine, "connect", _enable_sqlite_foreign_keys):
        event.listen(target_engine, "connect", _enable_sqlite_foreign_keys)
    return target_engine


configure_sqlite_foreign_keys(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
