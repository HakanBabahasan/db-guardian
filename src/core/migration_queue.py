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
