"""
DB Guardian — Bildirim Test Router.

Endpoints:
  POST /api/notifications/test   — Test bildirimi gönder (admin)
  GET  /api/notifications/config — Yapılandırma durumu
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.gateway.auth import require_role
from src.notifications.notifier import notification_service
from src.config import settings

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.post("/test")
async def test_notification(
    _admin=Depends(require_role("admin")),
):
    """Test bildirimi gönderir. Yapılandırılmış kanalları doğrular."""
    slack_sent = await notification_service.send_slack(
        "✅ DB Guardian bildirim testi başarılı!", level="success"
    )
    email_sent = notification_service.send_email(
        subject="Bildirim Testi",
        body="DB Guardian bildirim sistemi test edildi.",
    )
    return {
        "slack": "gönderildi" if slack_sent else "yapılandırılmamış veya başarısız",
        "email": "gönderildi" if email_sent else "yapılandırılmamış veya başarısız",
    }


@router.get("/config")
def notification_config(
    _admin=Depends(require_role("admin")),
):
    """Bildirim kanallarının yapılandırma durumunu gösterir."""
    slack_configured = bool(getattr(settings, "slack_webhook_url", None))
    email_configured = bool(getattr(settings, "smtp_host", None))
    return {
        "slack": {"configured": slack_configured},
        "email": {
            "configured": email_configured,
            "host": getattr(settings, "smtp_host", None),
            "to": getattr(settings, "smtp_to", None),
        },
    }
