"""
DB Guardian — Migration Kuyruğu.

• Tüm migration istekleri sırayla işlenir; eş zamanlı çalışma olmaz.
• Her iş unique bir job_id ile takip edilir.
• Arka plan asyncio task'ı kuyruğu işler.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

from src.models.schemas import DecisionResult, JobStatus, RiskLevel

logger = logging.getLogger("guardian.queue")


@dataclass
class MigrationJob:
    job_id: str
    sql: str
    submitted_by: str
    description: str | None
    status: JobStatus = JobStatus.QUEUED
    decision: DecisionResult | None = None
    risk_level: RiskLevel | None = None
    submitted_at: datetime = field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None
    message: str = ""
    diff_summary: dict[str, Any] | None = None
    snapshot_path: str | None = None   # rollback için
    callback: Callable[["MigrationJob"], Coroutine] | None = field(
        default=None, repr=False
    )


class MigrationQueue:
    """
    Seri işlem garantisi veren migration kuyruğu.

    İki yazılımcı aynı anda iş gönderirse ikincisi bekleye alınır;
    birinci tamamlanmadan ikinciye geçilmez.
    """

    def __init__(self):
        self._queue: asyncio.Queue[MigrationJob] = asyncio.Queue()
        self._jobs: dict[str, MigrationJob] = {}   # job_id → job
        self._running = False
        self._paused = False               # rollback sırasında kuyruk duraksar
        self._worker_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def add_job(
        self,
        sql: str,
        submitted_by: str,
        description: str | None,
        callback: Callable[[MigrationJob], Coroutine],
    ) -> MigrationJob:
        """Yeni bir iş kuyruğa ekler ve MigrationJob döner."""
        job = MigrationJob(
            job_id=str(uuid.uuid4()),
            sql=sql,
            submitted_by=submitted_by,
            description=description,
            callback=callback,
        )
        self._jobs[job.job_id] = job
        self._queue.put_nowait(job)
        logger.info(f"[{job.job_id}] Kuyruğa eklendi — kullanıcı: {submitted_by}")
        return job

    def get_job(self, job_id: str) -> MigrationJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[MigrationJob]:
        """Tüm işleri (yeni→eski sırayla) listeler."""
        return sorted(self._jobs.values(), key=lambda j: j.submitted_at, reverse=True)

    def pause(self):
        """
        Kuyruğu duraksatır — worker mevcut işi bitirir, yeni iş almaz.
        Rollback gibi kritik operasyonlar sırasında kullanılır.
        """
        self._paused = True
        logger.warning("Migration kuyruğu duraksatıldı (PAUSED).")

    def resume(self):
        """Duraksatılmış kuyruğu sürdürür."""
        self._paused = False
        logger.info("Migration kuyruğu devam ettiriliyor (RESUMED).")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def prune(self, max_size: int = 500):
        """
        Bellekte biriken eski işleri temizler.
        max_size aşılırsa terminal durumdaki (APPLIED/BLOCKED/FAILED/ROLLED_BACK)
        en eski işler silinir.
        """
        if len(self._jobs) <= max_size:
            return
        terminal = {
            JobStatus.APPLIED, JobStatus.BLOCKED, JobStatus.FAILED, JobStatus.ROLLED_BACK
        }
        candidates = sorted(
            [j for j in self._jobs.values() if j.status in terminal],
            key=lambda j: j.submitted_at,
        )
        to_delete = len(self._jobs) - max_size
        deleted = 0
        for job in candidates:
            if deleted >= to_delete:
                break
            del self._jobs[job.job_id]
            deleted += 1
        if deleted:
            logger.info(f"prune(): {deleted} eski iş bellekten temizlendi.")

    def queue_size(self) -> int:
        return self._queue.qsize()

    def active_job_id(self) -> str | None:
        for job in self._jobs.values():
            if job.status == JobStatus.PROCESSING:
                return job.job_id
        return None

    # ── Arka Plan İşçisi ──────────────────────────────────────────────────

    def start(self):
        """Uygulama başlangıcında çağrılır — arka plan task başlatır."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("Migration kuyruğu işçisi başlatıldı.")

    def stop(self):
        """Uygulama kapatılırken çağrılır."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

    async def _worker(self):
        """Asenkron arka plan döngüsü — işleri sırayla alır."""
        while self._running:
            # Kuyruk duraksatıldıysa bekle
            if self._paused:
                await asyncio.sleep(0.3)
                continue
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            job.status = JobStatus.PROCESSING
            logger.info(f"[{job.job_id}] İşleniyor...")

            try:
                if job.callback:
                    await job.callback(job)
            except Exception as exc:
                logger.error(f"[{job.job_id}] İşlem hatası: {exc}")
                job.status = JobStatus.FAILED
                job.message = f"Beklenmedik hata: {exc}"
                job.processed_at = datetime.utcnow()
            finally:
                self._queue.task_done()
                logger.info(f"[{job.job_id}] Tamamlandı — durum: {job.status}")


migration_queue = MigrationQueue()
