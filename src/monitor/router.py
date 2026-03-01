"""
DB Guardian — Monitor API Router.

Endpoints:
  GET  /api/status              — Sistem durumu
  POST /api/monitor/maintenance — Bakım moduna geç (admin)
  POST /api/monitor/monitoring  — İzleme moduna geç (admin)
  POST /api/monitor/resume      — Normal moda dön (admin)
  GET  /api/monitor/snapshots   — Mevcut backup'ları listele
"""
from fastapi import APIRouter, Depends

from src.audit.logger import log_event
from src.core.backup import backup_engine
from src.core.migration_queue import migration_queue
from src.gateway.auth import get_current_user, require_role
from src.models.schemas import SystemMode, SystemStatusResponse
from src.monitor.modes import system_mode

router = APIRouter(tags=["Monitor"])


@router.get("/api/status", response_model=SystemStatusResponse)
def get_status(_user=Depends(get_current_user)):
    """Sistemin anlık durumunu döner."""
    info = system_mode.status_info()
    return SystemStatusResponse(
        mode=info["mode"],
        queue_size=migration_queue.queue_size(),
        active_job=migration_queue.active_job_id(),
        uptime_seconds=system_mode.uptime_seconds(),
        message=info["reason"],
    )


@router.post("/api/monitor/maintenance")
def enter_maintenance(
    reason: str = "Manuel bakım modu.",
    _admin=Depends(require_role("admin", "manager")),
):
    system_mode.enter_maintenance(reason)
    return {"mode": SystemMode.MAINTENANCE, "message": "Bakım moduna girildi."}


@router.post("/api/monitor/monitoring")
def enter_monitoring(
    reason: str = "İzleme moduna geçildi.",
    _admin=Depends(require_role("admin", "manager")),
):
    system_mode.enter_monitoring(reason)
    return {"mode": SystemMode.MONITORING, "message": "İzleme moduna girildi."}


@router.post("/api/monitor/resume")
def resume_active(
    reason: str = "Normal çalışmaya devam.",
    _admin=Depends(require_role("admin", "manager")),
):
    system_mode.resume_active(reason)
    return {"mode": SystemMode.ACTIVE, "message": "Aktif moda dönüldü."}


@router.get("/api/monitor/snapshots")
def list_snapshots(_user=Depends(require_role("admin", "manager"))):
    """Mevcut backup dosyalarını listeler."""
    return {"snapshots": backup_engine.list_snapshots()}
