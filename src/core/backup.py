"""
DB Guardian — Backup / Snapshot Motoru.

Her tehlikeli işlem öncesinde pg_dump ile production'ın tam yedeğini alır.
Retention politikası: BACKUP_RETENTION_DAYS günden eski yedekler silinir.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.config import settings

logger = logging.getLogger("guardian.backup")


class BackupEngine:

    def __init__(self):
        self.backup_dir = Path(settings.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._env = {**os.environ, "PGPASSWORD": settings.prod_db_password}

    # ── Snapshot Al ──────────────────────────────────────────────────────

    def take_snapshot(self, job_id: str) -> dict:
        """
        Production DB'nin tam yedeğini alır.

        Returns:
            {"success": bool, "path": str, "elapsed": float}
        """
        start = time.time()
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        filename = f"snapshot_{timestamp}_{job_id[:8]}.dump"
        filepath = self.backup_dir / filename

        logger.info(f"[{job_id}] Snapshot alınıyor → {filepath}")

        cmd = [
            "pg_dump",
            "-h", settings.prod_db_host,
            "-p", str(settings.prod_db_port),
            "-U", settings.prod_db_user,
            "-d", settings.prod_db_name,
            "--format=custom",
            "--compress=6",
            f"--file={filepath}",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, env=self._env
        )

        elapsed = time.time() - start

        if result.returncode != 0:
            logger.error(f"[{job_id}] Snapshot başarısız: {result.stderr}")
            return {"success": False, "error": result.stderr, "elapsed": elapsed}

        size_mb = filepath.stat().st_size / (1024 * 1024) if filepath.exists() else 0
        logger.info(
            f"[{job_id}] Snapshot tamamlandı ({elapsed:.1f}s, {size_mb:.1f} MB): {filename}"
        )
        return {"success": True, "path": str(filepath), "filename": filename, "elapsed": elapsed}

    # ── Temizlik ─────────────────────────────────────────────────────────

    def cleanup_old_backups(self):
        """Retention politikasına göre eski yedekleri siler."""
        cutoff = datetime.utcnow() - timedelta(days=settings.backup_retention_days)
        deleted = 0
        for f in self.backup_dir.glob("snapshot_*.dump"):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                deleted += 1
                logger.info(f"Eski backup silindi: {f.name}")
        if deleted:
            logger.info(f"Toplam {deleted} eski backup temizlendi.")

    # ── Listeleme ────────────────────────────────────────────────────────

    def list_snapshots(self) -> list[dict]:
        """Mevcut snapshot'ları listeler."""
        snapshots = []
        for f in sorted(self.backup_dir.glob("snapshot_*.dump"), reverse=True):
            stat = f.stat()
            snapshots.append(
                {
                    "filename": f.name,
                    "path": str(f),
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
        return snapshots


backup_engine = BackupEngine()
