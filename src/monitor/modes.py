"""
DB Guardian — Sistem Modları.

  ACTIVE       → Normal çalışma
  MAINTENANCE  → Yazma kilitli, sadece okuma açık
  MONITORING   → İzleme modu — komutlara izin verilir ama her şey loglanır
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.models.schemas import SystemMode

logger = logging.getLogger("guardian.monitor")


class SystemModeManager:
    """
    Sistem modunu yönetir.

    Bakım moduna geçiş senaryoları:
      - Break-glass timeout → otomatik bakım modu
      - İki yönetici de yanıt vermezse → bakım modu

    İzleme modu senaryoları:
      - Guardian'ı tamamen kapatmak yerine izleme moduna geçebiliriz.
      - Çok tehlikeli komutlar hâlâ engellenir, ama diğerleri loglanarak geçer.
    """

    def __init__(self):
        self._mode = SystemMode.ACTIVE
        self._mode_changed_at = datetime.now(timezone.utc)
        self._mode_reason: str = "Sistem başlatıldı."
        self._start_time = datetime.now(timezone.utc)

    # ── Mod okuma ────────────────────────────────────────────────────────

    @property
    def mode(self) -> SystemMode:
        return self._mode

    @property
    def is_active(self) -> bool:
        return self._mode == SystemMode.ACTIVE

    @property
    def is_maintenance(self) -> bool:
        return self._mode == SystemMode.MAINTENANCE

    @property
    def is_monitoring(self) -> bool:
        return self._mode == SystemMode.MONITORING

    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self._start_time).total_seconds()

    # ── Mod geçişleri ─────────────────────────────────────────────────────

    def enter_maintenance(self, reason: str):
        """Bakım moduna geç — tüm yazma işlemleri durdurulur."""
        self._set_mode(SystemMode.MAINTENANCE, reason)
        self._alert_maintenance()

    def enter_monitoring(self, reason: str):
        """İzleme moduna geç — komutlar geçer ama loglanır."""
        self._set_mode(SystemMode.MONITORING, reason)
        logger.warning(f"[MOD] İzleme moduna geçildi: {reason}")

    def resume_active(self, reason: str):
        """Normal çalışmaya dön."""
        self._set_mode(SystemMode.ACTIVE, reason)
        logger.info(f"[MOD] Aktif moda dönüldü: {reason}")

    def _set_mode(self, mode: SystemMode, reason: str):
        prev = self._mode
        self._mode = mode
        self._mode_changed_at = datetime.now(timezone.utc)
        self._mode_reason = reason
        logger.warning(f"[MOD] {prev} → {mode} | Sebep: {reason}")

    # ── Durum bilgisi ─────────────────────────────────────────────────────

    def status_info(self) -> dict:
        return {
            "mode": self._mode,
            "reason": self._mode_reason,
            "changed_at": self._mode_changed_at.isoformat(),
            "uptime_seconds": self.uptime_seconds(),
        }

    # ── Bakım modu bildirimi ──────────────────────────────────────────────

    def _alert_maintenance(self):
        """
        Production'da: SMS + arama + e-posta.
        MVP'de: konsol çıktısı + log.
        """
        msg = (
            f"\n{'!'*60}\n"
            f"🔴  SİSTEM BAKIM MODUNA GEÇTİ\n"
            f"Sebep : {self._mode_reason}\n"
            f"Zaman : {self._mode_changed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"Durum : Tüm yazma işlemleri durduruldu. Sadece okuma açık.\n"
            f"Eylem : Yönetici müdahalesi gerekli.\n"
            f"POST /api/monitor/resume ile aktif moda dönün.\n"
            f"{'!'*60}"
        )
        logger.critical(msg)
        print(msg)


system_mode = SystemModeManager()
