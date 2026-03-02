"""
DB Guardian — Rollback Router.

Endpoints:
  POST /api/rollback/{job_id}   — APPLIED bir işi geri al
  GET  /api/rollback/history    — Rollback geçmişi
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.audit.logger import log_event
from src.core.migration_queue import migration_queue
from src.database import get_db
from src.gateway.auth import get_current_user, require_role
from src.models.schemas import JobStatus
from src.rollback.manager import rollback_engine

logger = logging.getLogger("guardian.rollback")

router = APIRouter(prefix="/api/rollback", tags=["Rollback"])


@router.post("/{job_id}")
async def rollback_job(
    job_id: str,
    current_user: dict = Depends(require_role("admin")),   # ● Sadece admin yetkili
    db: Session = Depends(get_db),
):
    """
    Belirtilen işi snapshot'tan geri alır.

    Kurallar:
    - Yalnızca APPLIED statüsündeki işler geri alınabilir.
    - Snapshot dosyasının disk üzerinde mevcut olması gerekir.
    - Yalnızca admin rolü bu endpoint'i çağırabilir (manager değil).
    - Rollback sırasında kuyruk dondurulur; tamamlanınca devam ettirilir.
    """
    username = current_user["username"]
    job = migration_queue.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"İş bulunamadı: {job_id}")

    if job.status != JobStatus.APPLIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Yalnızca APPLIED statüsündeki işler geri alınabilir. Mevcut durum: {job.status}",
        )

    snapshot_path = getattr(job, "snapshot_path", None)
    if not snapshot_path or not rollback_engine.snapshot_exists(snapshot_path):
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="Bu iş için snapshot dosyası bulunamadı. Rollback mümkün değil.",
        )

    log_event(
        db, actor=username, action="ROLLBACK_START",
        job_id=job_id,
        details={"snapshot": snapshot_path, "triggered_by": username},
    )

    # Rollback sırasında yeni iş alınmasını engelle
    migration_queue.pause()
    try:
        result = rollback_engine.restore(snapshot_path, job_id)
    finally:
        migration_queue.resume()   # Hata olsa bile kuyruğu devam ettir

    if not result["success"]:
        log_event(
            db, actor=username, action="ROLLBACK_FAILED",
            job_id=job_id,
            details={"error": result["error"]},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rollback başarısız: {result['error']}",
        )

    job.status = JobStatus.ROLLED_BACK
    job.message = (
        f"[{username}] tarafından geri alındı. "
        f"Süre: {result['elapsed']:.1f}s. Snapshot: {snapshot_path}"
    )
    job.processed_at = datetime.utcnow()

    log_event(
        db, actor=username, action="ROLLBACK_OK",
        job_id=job_id,
        details={"elapsed": result["elapsed"], "snapshot": snapshot_path},
    )

    return {
        "job_id": job_id,
        "status": "ROLLED_BACK",
        "elapsed": result["elapsed"],
        "message": f"Production başarıyla geri yüklendi. Snapshot: {snapshot_path}",
    }


@router.get("/history")
def rollback_history(
    _user=Depends(require_role("admin", "manager")),
):
    """Daha önce rollback yapılmış işlerin listesi."""
    rolled_back = [
        {
            "job_id": j.job_id,
            "submitted_by": j.submitted_by,
            "sql": j.sql[:100] + ("..." if len(j.sql) > 100 else ""),
            "processed_at": j.processed_at.isoformat() if j.processed_at else None,
            "message": j.message,
        }
        for j in migration_queue.list_jobs()
        if j.status == JobStatus.ROLLED_BACK
    ]
    return {"total": len(rolled_back), "rollbacks": rolled_back}
