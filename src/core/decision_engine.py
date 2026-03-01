"""
DB Guardian — Karar Motoru.

Diff analizi + test sonuçlarını alır, son kararı üretir:
  PASS            → Production'a otomatik uy
  MANUAL_REVIEW   → Break-glass (iki yönetici onayı) gerekli
  BLOCK           → Reddedildi, production'a dokunulmaz
  INSTANT_BLOCK   → Tehlikeli komut filtresinden geldi
"""
from __future__ import annotations

from src.models.schemas import DecisionResult, DiffResult, RiskLevel


class DecisionEngine:
    """
    Diff sonucuna ve isteğe bağlı test sonuçlarına göre
    karar üretir.
    """

    def decide(
        self,
        diff: DiffResult,
        apply_error: str | None = None,
    ) -> tuple[DecisionResult, str]:
        """
        Returns:
            (DecisionResult, human-readable explanation)
        """

        # SQL klona uygulanamadıysa → BLOCK
        if apply_error:
            return (
                DecisionResult.BLOCK,
                f"SQL klona uygulanırken hata oluştu: {apply_error}",
            )

        risk = diff.risk_level

        # Refactor-only → güvenli
        if diff.is_refactor_only:
            return (
                DecisionResult.PASS,
                "Yalnızca sıralama/refactor değişikliği tespit edildi. Güvenli.",
            )

        if risk == RiskLevel.LOW:
            return (
                DecisionResult.PASS,
                "Risk düşük, değişiklik güvenli görünüyor. Otomatik onaylandı.",
            )

        if risk == RiskLevel.MEDIUM:
            # Satır kaybı yoksa otomatik onayla
            if diff.total_row_loss == 0 and not _has_dangerous_schema_change(diff):
                return (
                    DecisionResult.PASS,
                    "Orta risk, ancak satır kaybı veya şema tehditi yok. Otomatik onaylandı.",
                )
            return (
                DecisionResult.MANUAL_REVIEW,
                f"Orta risk, dikkat edilmesi gereken değişiklikler var:\n"
                + "\n".join(f"  • {r}" for r in diff.risk_reasons),
            )

        if risk == RiskLevel.HIGH:
            return (
                DecisionResult.MANUAL_REVIEW,
                f"Yüksek risk! İki yönetici onayı gerekli:\n"
                + "\n".join(f"  • {r}" for r in diff.risk_reasons),
            )

        # CRITICAL
        return (
            DecisionResult.BLOCK,
            f"KRİTİK RİSK — değişiklik reddedildi:\n"
            + "\n".join(f"  • {r}" for r in diff.risk_reasons),
        )


def _has_dangerous_schema_change(diff: DiffResult) -> bool:
    """Silinen kolon veya tip küçültme var mı?"""
    for table in diff.tables:
        if table.dropped_columns:
            return True
        if table.type_changes:
            return True
    return False


decision_engine = DecisionEngine()
