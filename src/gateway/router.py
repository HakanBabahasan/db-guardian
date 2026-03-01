"""
DB Guardian — Ana Gateway Router.

Endpoints:
  POST /api/execute           — SQL komutu gönder
  GET  /api/jobs/{job_id}     — İş durumu sorgula
  GET  /api/jobs              — Tüm işleri listele (admin)
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.audit.logger import log_event
from src.breakglass.manager import breakglass_manager
from src.core.backup import backup_engine
from src.core.clone_engine import clone_engine
from src.core.command_filter import FilterDecision, check as filter_check
from src.core.decision_engine import decision_engine
from src.core.diff_analyzer import diff_analyzer, take_db_snapshot
from src.core.migration_queue import MigrationJob, migration_queue
from src.database import get_db
from src.gateway.auth import get_current_user, require_role
from src.models.schemas import (
    DecisionResult,
    ExecuteRequest,
    ExecuteResponse,
    JobStatus,
    JobStatusResponse,
    RiskLevel,
    SystemMode,
)
from src.monitor.modes import system_mode

logger = logging.getLogger("guardian.gateway")

router = APIRouter(prefix="/api", tags=["Gateway"])


# ── SQL Çalıştırma ──────────────────────────────────────────────────────────

@router.post("/execute", response_model=ExecuteResponse)
async def execute_sql(
    req: ExecuteRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    SQL komutunu Guardian pipeline'ına gönderir.

    1. Bakım modunda ise yazma reddedilir.
    2. Tehlikeli komut filtresi çalışır.
    3. Güvenli komutlar kuyruğa alınır, arka planda işlenir.
    """
    username = current_user["username"]

    # ── 1. Bakım modu kontrolü ───────────────────────────────────────────
    if system_mode.is_maintenance:
        log_event(
            db, actor=username, action="BLOCKED_MAINTENANCE",
            sql_command=req.sql, decision="BLOCK",
            details={"reason": "Sistem bakım modunda."},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sistem bakım modunda. Yazma işlemleri geçici olarak durdurulmuş.",
        )

    # ── 2. Komut filtresi ─────────────────────────────────────────────────
    filter_result = filter_check(req.sql)

    if filter_result.decision == FilterDecision.INSTANT_BLOCK:
        log_event(
            db, actor=username, action="INSTANT_BLOCK",
            sql_command=req.sql, decision="INSTANT_BLOCK",
            risk_level="CRITICAL",
            details={"rule": filter_result.matched_rule, "reason": filter_result.reason},
        )
        return ExecuteResponse(
            job_id="N/A",
            status=JobStatus.BLOCKED,
            decision=DecisionResult.INSTANT_BLOCK,
            message=filter_result.reason,
            risk_level=RiskLevel.CRITICAL,
            submitted_by=username,
            submitted_at=datetime.utcnow(),
        )

    # ── 3. Kuyruğa ekle ───────────────────────────────────────────────────
    job = migration_queue.add_job(
        sql=req.sql,
        submitted_by=username,
        description=req.description,
        callback=_process_job_callback,
    )

    log_event(
        db, actor=username, action="QUEUED",
        job_id=job.job_id, sql_command=req.sql,
        details={"description": req.description, "filter": filter_result.decision},
    )

    return ExecuteResponse(
        job_id=job.job_id,
        status=JobStatus.QUEUED,
        message=f"Komut kuyruğa alındı. Kuyruk büyüklüğü: {migration_queue.queue_size()}",
        submitted_by=username,
        submitted_at=job.submitted_at,
    )


# ── İş Durumu ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    _user=Depends(get_current_user),
):
    """Belirli bir migration işinin durumunu döner."""
    job = migration_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"İş bulunamadı: {job_id}")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        decision=job.decision,
        risk_level=job.risk_level,
        submitted_by=job.submitted_by,
        submitted_at=job.submitted_at,
        processed_at=job.processed_at,
        message=job.message,
        diff_summary=job.diff_summary,
    )


@router.get("/jobs")
def list_jobs(_admin=Depends(require_role("admin", "manager"))):
    """Tüm işleri listeler."""
    jobs = list(migration_queue._jobs.values())
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status,
                "decision": j.decision,
                "submitted_by": j.submitted_by,
                "submitted_at": j.submitted_at.isoformat(),
            }
            for j in sorted(jobs, key=lambda x: x.submitted_at, reverse=True)
        ],
    }


# ── Pipeline Callback ─────────────────────────────────────────────────────────

async def _process_job_callback(job: MigrationJob):
    """
    Kuyruktaki her iş için async pipeline.
    Bu fonksiyon migration_queue worker tarafından çağrılır.
    """
    from src.database import SessionLocal

    db = SessionLocal()
    try:
        await _run_pipeline(job, db)
    finally:
        db.close()


async def _run_pipeline(job: MigrationJob, db):
    """
    6 aşamalı Guardian pipeline'ı:
      1. Snapshot (pre-operation backup)
      2. Klon oluştur
      3. SQL'i klona uygula
      4. Diff analizi
      5. Karar
      6. Production'a uygula (onaylandıysa)
    """
    import asyncio

    jid = job.job_id
    logger.info(f"[{jid}] Pipeline başladı.")

    # ── Aşama 1: Pre-operation snapshot ─────────────────────────────────
    log_event(db, actor="guardian", action="SNAPSHOT_START", job_id=jid)
    snap = backup_engine.take_snapshot(jid)
    if not snap["success"]:
        # Snapshot başarısız → hata ama devam et (MVP'de uyarı yeterli)
        logger.warning(f"[{jid}] Snapshot başarısız: {snap.get('error')}")
        log_event(db, actor="guardian", action="SNAPSHOT_FAILED", job_id=jid,
                  details={"error": snap.get("error")})
    else:
        log_event(db, actor="guardian", action="SNAPSHOT_OK", job_id=jid,
                  details={"file": snap.get("filename"), "elapsed": snap.get("elapsed")})

    # ── Aşama 2: Klon oluştur ─────────────────────────────────────────────
    log_event(db, actor="guardian", action="CLONE_START", job_id=jid)
    clone_result = clone_engine.create_clone(jid)
    if not clone_result["success"]:
        job.status = JobStatus.FAILED
        job.message = f"Klon oluşturulamadı: {clone_result.get('error')}"
        job.processed_at = datetime.utcnow()
        log_event(db, actor="guardian", action="CLONE_FAILED", job_id=jid,
                  details={"error": clone_result.get("error")})
        return
    log_event(db, actor="guardian", action="CLONE_OK", job_id=jid,
              details={"elapsed": clone_result.get("elapsed")})

    # ── Aşama 3: Production snapshot al (diff için) ───────────────────────
    from src.config import settings
    prod_snapshot = take_db_snapshot(settings.prod_dsn)

    # ── Aşama 4: SQL'i klona uygula ──────────────────────────────────────
    log_event(db, actor="guardian", action="APPLY_TO_CLONE", job_id=jid,
              sql_command=job.sql)
    apply_result = clone_engine.apply_sql_to_clone(job.sql, jid)
    apply_error = None if apply_result["success"] else apply_result.get("error", "Bilinmeyen hata")

    if apply_error:
        log_event(db, actor="guardian", action="APPLY_FAILED", job_id=jid,
                  details={"error": apply_error})

    # ── Aşama 5: Diff analizi ─────────────────────────────────────────────
    clone_snapshot = take_db_snapshot(settings.clone_dsn)
    diff = diff_analyzer.analyze(prod_snapshot, clone_snapshot)

    log_event(db, actor="guardian", action="DIFF_COMPLETE", job_id=jid,
              risk_level=diff.risk_level,
              details={"summary": diff.summary, "total_row_loss": diff.total_row_loss})

    # ── Aşama 6: Karar ───────────────────────────────────────────────────
    decision, decision_msg = decision_engine.decide(diff, apply_error)
    job.risk_level = diff.risk_level
    job.diff_summary = {
        "risk_level": diff.risk_level,
        "risk_reasons": diff.risk_reasons,
        "total_row_loss": diff.total_row_loss,
        "is_refactor_only": diff.is_refactor_only,
        "summary": diff.summary,
    }

    log_event(db, actor="guardian", action="DECISION", job_id=jid,
              decision=decision, risk_level=diff.risk_level,
              details={"message": decision_msg})

    if decision == DecisionResult.BLOCK:
        job.status = JobStatus.BLOCKED
        job.decision = decision
        job.message = decision_msg
        job.processed_at = datetime.utcnow()
        logger.warning(f"[{jid}] BLOK: {decision_msg}")
        return

    if decision == DecisionResult.MANUAL_REVIEW:
        # Break-glass başlat
        job.status = JobStatus.AWAITING_APPROVAL
        job.decision = decision
        job.message = decision_msg
        session = breakglass_manager.request(
            job_id=jid,
            reason=decision_msg,
            requested_by=job.submitted_by,
        )
        log_event(db, actor="guardian", action="BREAKGLASS_REQUESTED", job_id=jid,
                  details={"reason": decision_msg})

        # İki yönetici onayını bekle
        approved = await breakglass_manager.wait_for_approval(jid)

        if not approved:
            job.status = JobStatus.BLOCKED
            job.message = "Break-glass onayı alınamadı (timeout veya reddedildi). Sistem bakım moduna geçti."
            job.processed_at = datetime.utcnow()
            system_mode.enter_maintenance("Break-glass onayı alınamadı.")
            log_event(db, actor="guardian", action="BREAKGLASS_TIMEOUT", job_id=jid)
            return

        log_event(db, actor="guardian", action="BREAKGLASS_APPROVED", job_id=jid,
                  details={"approvals": session.approvals})

    # ── Aşama 7: Production'a uygula ─────────────────────────────────────
    log_event(db, actor="guardian", action="APPLY_TO_PROD", job_id=jid,
              sql_command=job.sql)

    import psycopg2
    try:
        conn = psycopg2.connect(settings.prod_dsn)
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(job.sql)
        conn.commit()
        cur.close()
        conn.close()

        job.status = JobStatus.APPLIED
        job.decision = DecisionResult.PASS
        job.message = f"Production'a başarıyla uygulandı. {decision_msg}"
        job.processed_at = datetime.utcnow()

        log_event(db, actor="guardian", action="APPLIED_OK", job_id=jid,
                  decision="PASS", risk_level=diff.risk_level)
        logger.info(f"[{jid}] ✓ Production'a uygulandı.")

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.message = f"Production'a uygulama başarısız: {exc}"
        job.processed_at = datetime.utcnow()
        log_event(db, actor="guardian", action="APPLY_PROD_FAILED", job_id=jid,
                  details={"error": str(exc)})
        logger.error(f"[{jid}] Production uygulama hatası: {exc}")
