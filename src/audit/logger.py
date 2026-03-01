"""
DB Guardian — Audit Logger.

Her önemli olay buraya yazılır:
  - Gönderilen SQL komutları
  - Anlık blok kararları
  - Klon / diff / karar sonuçları
  - Break-glass başvuruları ve onayları
  - Bakım modu geçişleri
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from src.audit.models import AuditLog

logger = logging.getLogger("guardian.audit")


def log_event(
    db: Session,
    actor: str,
    action: str,
    job_id: str | None = None,
    sql_command: str | None = None,
    decision: str | None = None,
    risk_level: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Audit log'a tek satır yazar.

    Parameterler:
        actor      : İşlemi yapan kullanıcı adı
        action     : Eylem kodu, örn: "EXECUTE", "INSTANT_BLOCK", "CLONE_START",
                     "DIFF_COMPLETE", "BREAKGLASS_REQUEST", "APPROVE", "MAINTENANCE_MODE"
        job_id     : İlgili migration job ID'si
        sql_command: Gönderilen SQL
        decision   : PASS | BLOCK | MANUAL_REVIEW | INSTANT_BLOCK
        risk_level : LOW | MEDIUM | HIGH | CRITICAL
        details    : JSON ek bilgi (diff özeti, hata mesajı vb.)
    """
    entry = AuditLog(
        job_id=job_id,
        actor=actor,
        action=action,
        sql_command=sql_command[:4000] if sql_command else None,  # uzunluk sınırı
        decision=decision,
        risk_level=risk_level,
        details=details,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(
        f"AUDIT | actor={actor} action={action} job={job_id} decision={decision}"
    )
    return entry
