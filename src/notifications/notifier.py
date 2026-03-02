"""
DB Guardian — Bildirim Sistemi.

Desteklenen kanallar:
  • Slack Webhook (SLACK_WEBHOOK_URL env değişkeni)
  • E-posta / SMTP (SMTP_* env değişkenleri)

Her ikisi de isteğe bağlı. Yapılandırılmamışsa sessizce atlanır.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger("guardian.notifications")


# ── Bildirim olayları ────────────────────────────────────────────────────────

NOTIFY_EVENTS = {
    "MANUAL_REVIEW",   # Break-glass gerektiriyor
    "BLOCK",           # İşlem engellendi
    "INSTANT_BLOCK",   # Anında engel
    "ROLLBACK_OK",     # Geri alma tamamlandı
    "ROLLBACK_FAILED", # Geri alma başarısız
    "BREAKGLASS_APPROVED",  # İki onay alındı
    "BREAKGLASS_TIMEOUT",   # Onay alınamadı
}


class NotificationService:
    """Asenkron bildirim gönderici."""

    # ── Slack ────────────────────────────────────────────────────────────

    async def send_slack(self, message: str, level: str = "info") -> bool:
        """
        Slack webhook'una mesaj gönderir.
        SLACK_WEBHOOK_URL ayarlanmamışsa hiçbir şey yapmaz.
        """
        url = getattr(settings, "slack_webhook_url", None)
        if not url:
            return False

        emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}.get(level, "📋")
        payload = {
            "text": f"{emoji} *DB Guardian*\n{message}",
            "username": "DB Guardian",
            "icon_emoji": ":shield:",
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.debug("Slack bildirimi gönderildi.")
                    return True
                else:
                    logger.warning(f"Slack yanıt kodu: {resp.status_code}")
                    return False
        except Exception as exc:
            logger.warning(f"Slack bildirim hatası: {exc}")
            return False

    # ── E-posta ──────────────────────────────────────────────────────────

    def send_email(self, subject: str, body: str) -> bool:
        """
        SMTP ile e-posta gönderir.
        SMTP_HOST ayarlanmamışsa hiçbir şey yapmaz.
        """
        smtp_host = getattr(settings, "smtp_host", None)
        smtp_to = getattr(settings, "smtp_to", None)
        if not smtp_host or not smtp_to:
            return False

        smtp_port = getattr(settings, "smtp_port", 587)
        smtp_user = getattr(settings, "smtp_user", "")
        smtp_password = getattr(settings, "smtp_password", "")
        smtp_from = getattr(settings, "smtp_from", smtp_user)

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[DB Guardian] {subject}"
            msg["From"] = smtp_from
            msg["To"] = smtp_to

            text_part = MIMEText(body, "plain", "utf-8")
            html_part = MIMEText(
                f"<pre style='font-family:monospace'>{body}</pre>", "html", "utf-8"
            )
            msg.attach(text_part)
            msg.attach(html_part)

            ctx = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls(context=ctx)
                if smtp_user:
                    server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, smtp_to.split(","), msg.as_string())

            logger.debug(f"E-posta gönderildi: {subject}")
            return True
        except Exception as exc:
            logger.warning(f"E-posta gönderim hatası: {exc}")
            return False

    # ── Ana gönderici ─────────────────────────────────────────────────────

    async def notify(
        self,
        event: str,
        job_id: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Olayı Slack + e-posta ile bildirir.
        Bildirim kanalı yapılandırılmamışsa sessizce atlanır.
        """
        if event not in NOTIFY_EVENTS:
            return

        lines = [
            f"Olay   : {event}",
            f"İş ID  : {job_id}",
            f"Aktör  : {actor}",
        ]
        if details:
            for k, v in details.items():
                lines.append(f"{k:<8}: {v}")
        message = "\n".join(lines)

        level_map = {
            "MANUAL_REVIEW": "warning",
            "BLOCK": "error",
            "INSTANT_BLOCK": "error",
            "ROLLBACK_OK": "success",
            "ROLLBACK_FAILED": "error",
            "BREAKGLASS_APPROVED": "success",
            "BREAKGLASS_TIMEOUT": "error",
        }
        level = level_map.get(event, "info")

        await self.send_slack(message, level)
        self.send_email(subject=f"{event} — Job {job_id[:8]}", body=message)


notification_service = NotificationService()
