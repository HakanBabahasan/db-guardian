"""
DB Guardian — Pydantic şemaları (request / response modelleri).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Enum'lar ────────────────────────────────────────────────────────────────

class CommandType(str, Enum):
    DDL = "DDL"   # ALTER, DROP, CREATE, TRUNCATE
    DML = "DML"   # INSERT, UPDATE, DELETE
    DQL = "DQL"   # SELECT (yalnızca okuma)
    OTHER = "OTHER"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionResult(str, Enum):
    PASS = "PASS"               # Otomatik onay
    MANUAL_REVIEW = "MANUAL_REVIEW"   # Break-glass gerekli
    BLOCK = "BLOCK"             # Reddedildi
    INSTANT_BLOCK = "INSTANT_BLOCK"   # Anında reddedildi (tehlikeli komut)


class SystemMode(str, Enum):
    ACTIVE = "ACTIVE"           # Normal çalışma
    MAINTENANCE = "MAINTENANCE" # Yazma kilitli, sadece okuma
    MONITORING = "MONITORING"   # İzleme modu (izin ver ama logla)


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class BreakGlassStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"       # 1 yönetici onayladı
    APPROVED = "APPROVED"     # 2 yönetici onayladı
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


# ── Auth ────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    username: str
    role: str
    full_name: str | None = None


# ── SQL Çalıştırma ───────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    sql: str = Field(..., description="Çalıştırılacak SQL komutu")
    description: str | None = Field(None, description="Bu değişikliğin amacı")
    target_tables: list[str] | None = Field(None, description="Etkilenen tablolar (isteğe bağlı)")


class ExecuteResponse(BaseModel):
    job_id: str
    status: JobStatus
    decision: DecisionResult | None = None
    message: str
    risk_level: RiskLevel | None = None
    submitted_by: str
    submitted_at: datetime


# ── Kuyruktaki İş ────────────────────────────────────────────────────────────

class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    decision: DecisionResult | None = None
    risk_level: RiskLevel | None = None
    submitted_by: str
    submitted_at: datetime
    processed_at: datetime | None = None
    message: str | None = None
    diff_summary: dict[str, Any] | None = None


# ── Diff Analizi ─────────────────────────────────────────────────────────────

class TableDiff(BaseModel):
    table_name: str
    before_row_count: int
    after_row_count: int
    row_delta: int
    null_changes: dict[str, int] = Field(default_factory=dict)
    type_changes: dict[str, tuple[str, str]] = Field(default_factory=dict)
    dropped_columns: list[str] = Field(default_factory=list)
    added_columns: list[str] = Field(default_factory=list)
    constraint_changes: list[str] = Field(default_factory=list)


class DiffResult(BaseModel):
    tables: list[TableDiff] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    risk_reasons: list[str] = Field(default_factory=list)
    is_refactor_only: bool = False
    total_row_loss: int = 0
    summary: str = ""


# ── Break-Glass ──────────────────────────────────────────────────────────────

class BreakGlassRequest(BaseModel):
    job_id: str
    reason: str = Field(..., description="Neden manuel onay gerekiyor?")


class BreakGlassApprove(BaseModel):
    job_id: str
    manager_id: str
    daily_password: str = Field(..., description="Günlük değişen parola")


class BreakGlassStatusResponse(BaseModel):
    job_id: str
    status: BreakGlassStatus
    approvals: list[str] = Field(default_factory=list)
    required_approvals: int = 2
    expires_at: datetime | None = None
    message: str


# ── Audit Log ────────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    job_id: str | None = None
    actor: str
    action: str
    sql_command: str | None = None
    decision: str | None = None
    risk_level: str | None = None
    details: dict[str, Any] | None = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogList(BaseModel):
    total: int
    entries: list[AuditLogEntry]


# ── Sistem Durumu ─────────────────────────────────────────────────────────────

class SystemStatusResponse(BaseModel):
    mode: SystemMode
    queue_size: int
    active_job: str | None = None
    pending_breakglass: int = 0
    uptime_seconds: float
    last_successful_operation: datetime | None = None
    message: str
