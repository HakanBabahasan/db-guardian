"""
DB Guardian — Audit Log veritabanı modeli (SQLAlchemy).
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from src.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    actor = Column(String(100), nullable=False)        # kim yaptı
    action = Column(String(100), nullable=False)       # ne yaptı (EXECUTE, BLOCK, APPROVE, …)
    sql_command = Column(Text, nullable=True)           # gönderilen SQL
    decision = Column(String(30), nullable=True)        # PASS, BLOCK, MANUAL_REVIEW
    risk_level = Column(String(20), nullable=True)      # LOW, HIGH, CRITICAL
    details = Column(JSONB, nullable=True)              # ek detaylar (diff özeti vb.)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
