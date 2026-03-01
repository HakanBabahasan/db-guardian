"""
DB Guardian — SQLAlchemy bağlantı ve session yönetimi.
Uygulama DB'si audit log, kullanıcı ve break-glass kayıtları için kullanılır.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from src.config import settings

# Uygulama DB (audit, users, break-glass)
engine = create_engine(
    settings.app_dsn,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI bağımlılığı — her request için DB session döner."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
