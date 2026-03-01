"""
DB Guardian — Break-Glass Mekaniği.

Tehlikeli bir işlem için iki farklı yöneticinin:
  1. Fiziksel sistem girişi (JWT)
  2. Günlük değişen parola girişi

ile onay vermesi gerekir.

İşleyiş:
  → Sistem MANUAL_REVIEW kararı üretir
  → BreakGlassManager.request() çağrılır — bildirim gönderilir
  → manager1 /api/breakglass/approve → PARTIAL
  → manager2 /api/breakglass/approve → APPROVED → işlem kuyruğuna geri döner
  → Timeout dolunca EXPIRED → iş BLOCKED olur
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.config import settings
from src.gateway.auth import verify_daily_password
from src.models.schemas import BreakGlassStatus

logger = logging.getLogger("guardian.breakglass")


@dataclass
class BreakGlassSession:
    job_id: str
    reason: str
    requested_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    approvals: list[str] = field(default_factory=list)   # onaylayan manager'lar
    status: BreakGlassStatus = BreakGlassStatus.PENDING
    approved_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class BreakGlassManager:
    """
    Break-glass akışını yönetir.
    """

    def __init__(self):
        self._sessions: dict[str, BreakGlassSession] = {}

    # ── Talep ────────────────────────────────────────────────────────────

    def request(self, job_id: str, reason: str, requested_by: str) -> BreakGlassSession:
        """Yeni bir break-glass oturumu başlatır."""
        session = BreakGlassSession(
            job_id=job_id,
            reason=reason,
            requested_by=requested_by,
        )
        # Timeout hesapla
        from datetime import timedelta

        session.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.breakglass_timeout_seconds
        )
        self._sessions[job_id] = session

        self._send_notifications(session)
        logger.warning(
            f"[{job_id}] BREAK-GLASS talep edildi | kullanıcı: {requested_by} | sebep: {reason}"
        )
        return session

    def get_session(self, job_id: str) -> BreakGlassSession | None:
        return self._sessions.get(job_id)

    # ── Onay ─────────────────────────────────────────────────────────────

    def approve(
        self, job_id: str, manager_id: str, daily_password: str
    ) -> tuple[bool, str]:
        """
        Yönetici onayı işler.

        Returns:
            (success: bool, message: str)
        """
        session = self._sessions.get(job_id)
        if session is None:
            return False, f"Break-glass oturumu bulunamadı: {job_id}"

        # Süresi dolmuş mu?
        if datetime.now(timezone.utc) > session.expires_at:
            session.status = BreakGlassStatus.EXPIRED
            return False, "Break-glass oturumunun süresi dolmuş."

        if session.status in (BreakGlassStatus.APPROVED, BreakGlassStatus.EXPIRED):
            return False, f"Oturum artık {session.status} durumunda."

        # Aynı kişi iki kez onaylayamaz
        if manager_id in session.approvals:
            return False, f"{manager_id} zaten onayladı. Farklı bir yönetici gerekli."

        # Günlük parola doğrulama
        if not verify_daily_password(manager_id, daily_password):
            logger.warning(
                f"[{job_id}] Yanlış günlük parola — yönetici: {manager_id}"
            )
            return False, "Günlük parola hatalı."

        session.approvals.append(manager_id)
        logger.warning(
            f"[{job_id}] Break-glass onayı ({len(session.approvals)}/2) — yönetici: {manager_id}"
        )

        if len(session.approvals) >= 2:
            session.status = BreakGlassStatus.APPROVED
            session.approved_event.set()
            logger.warning(f"[{job_id}] İki yönetici onayı tamamlandı. İşlem serbest bırakıldı.")
            return True, "İki yönetici onayı tamamlandı. İşlem production'a uygulanacak."

        session.status = BreakGlassStatus.PARTIAL
        remaining = 2 - len(session.approvals)
        return True, f"Onay alındı ({len(session.approvals)}/2). {remaining} onay daha gerekli."

    # ── Bekleme ──────────────────────────────────────────────────────────

    async def wait_for_approval(self, job_id: str) -> bool:
        """
        İki yönetici onaylayana veya süre dolana kadar bekler.

        Returns:
            True → onaylandı, False → reddedildi / süresi doldu
        """
        session = self._sessions.get(job_id)
        if session is None:
            return False

        timeout = settings.breakglass_timeout_seconds
        try:
            await asyncio.wait_for(session.approved_event.wait(), timeout=float(timeout))
            return session.status == BreakGlassStatus.APPROVED
        except asyncio.TimeoutError:
            session.status = BreakGlassStatus.EXPIRED
            logger.warning(
                f"[{job_id}] Break-glass süresi doldu ({timeout}s). Bakım moduna geçiliyor."
            )
            return False

    # ── Bildirim ─────────────────────────────────────────────────────────

    def _send_notifications(self, session: BreakGlassSession):
        """
        Yöneticilere bildirim gönderir.
        MVP'de loglama + konsol çıktısı yeterli.
        Production'da: SMS + e-posta + push notification.
        """
        msg = (
            f"\n{'='*60}\n"
            f"⚠️  BREAK-GLASS TALEBİ\n"
            f"İş ID : {session.job_id}\n"
            f"Talep eden: {session.requested_by}\n"
            f"Sebep  : {session.reason}\n"
            f"Bitiş  : {session.expires_at.strftime('%H:%M:%S UTC')}\n"
            f"Onay için: POST /api/breakglass/approve\n"
            f"{'='*60}"
        )
        logger.critical(msg)
        print(msg)


breakglass_manager = BreakGlassManager()
