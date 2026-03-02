"""
DB Guardian — Rollback Motoru.

APPLIED durumundaki bir işi, önceden alınmış snapshot'tan geri alır.
Rollback kendisi de Guardian pipeline'ından geçer:
  snapshot_path mevcut → pg_restore → audit log.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from src.config import settings

logger = logging.getLogger("guardian.rollback")


class RollbackEngine:
    """Snapshot dosyasından production'ı geri yükler."""

    def __init__(self):
        self._env = {**os.environ, "PGPASSWORD": settings.prod_db_password}

    def restore(self, snapshot_path: str, job_id: str) -> dict:
        """
        Verilen snapshot dosyasından production DB'yi geri yükler.

        Strateji:
          1. Snapshot dosyasının varlığını kontrol et.
          2. pg_restore --clean ile mevcut şemayı temizleyip geri yükle.
          3. Sonucu döndür.

        Returns:
            {"success": bool, "elapsed": float, "error": str | None}
        """
        start = time.time()
        path = Path(snapshot_path)

        if not path.exists():
            msg = f"Snapshot dosyası bulunamadı: {snapshot_path}"
            logger.error(f"[{job_id}] {msg}")
            return {"success": False, "error": msg, "elapsed": 0.0}

        logger.info(f"[{job_id}] Rollback başlatılıyor → {path.name}")

        cmd = [
            "pg_restore",
            "-h", settings.prod_db_host,
            "-p", str(settings.prod_db_port),
            "-U", settings.prod_db_user,
            "-d", settings.prod_db_name,
            "--clean",
            "--if-exists",
            "--no-acl",
            "--no-owner",
            "--exit-on-error",
            str(path),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, env=self._env
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            logger.error(f"[{job_id}] Rollback başarısız: {result.stderr}")
            return {"success": False, "error": result.stderr, "elapsed": elapsed}

        logger.info(f"[{job_id}] Rollback tamamlandı ({elapsed:.1f}s).")
        return {"success": True, "elapsed": elapsed, "error": None}

    def snapshot_exists(self, snapshot_path: str) -> bool:
        return Path(snapshot_path).exists() if snapshot_path else False


rollback_engine = RollbackEngine()
