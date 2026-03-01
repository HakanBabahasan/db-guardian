"""
DB Guardian — Audit Log API Router.

Endpoints:
  GET /api/audit/logs         — Tüm log kayıtlarını listeler (sayfalı)
  GET /api/audit/logs/{job_id}— Belirli bir işe ait loglar
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.audit.models import AuditLog
from src.database import get_db
from src.gateway.auth import require_role
from src.models.schemas import AuditLogEntry, AuditLogList

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs", response_model=AuditLogList)
def list_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    actor: str | None = Query(None),
    action: str | None = Query(None),
    db: Session = Depends(get_db),
    _current_user=Depends(require_role("admin", "manager")),
):
    """Audit loglarını döner. Admin ve manager rolü gerektirir."""
    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if actor:
        q = q.filter(AuditLog.actor == actor)
    if action:
        q = q.filter(AuditLog.action == action)

    total = q.count()
    entries = q.offset(skip).limit(limit).all()
    return AuditLogList(total=total, entries=entries)


@router.get("/logs/{job_id}", response_model=AuditLogList)
def logs_by_job(
    job_id: str,
    db: Session = Depends(get_db),
    _current_user=Depends(require_role("admin", "manager", "developer")),
):
    """Belirli bir job_id'ye ait tüm log satırlarını döner."""
    q = db.query(AuditLog).filter(AuditLog.job_id == job_id).order_by(AuditLog.timestamp)
    entries = q.all()
    return AuditLogList(total=len(entries), entries=entries)
