"""
Karar Motoru Testleri — src/core/decision_engine.py

Dif sonucuna göre doğru kararın üretildiğini doğrular.
"""
import pytest
from src.core.decision_engine import decision_engine
from src.models.schemas import DecisionResult, DiffResult, RiskLevel, TableDiff


def make_diff(
    risk: RiskLevel = RiskLevel.LOW,
    is_refactor: bool = False,
    row_loss: int = 0,
    reasons: list[str] | None = None,
    dropped_cols: bool = False,
    type_changes: bool = False,
) -> DiffResult:
    tables = []
    if dropped_cols or type_changes:
        tables.append(TableDiff(
            table_name="users",
            before_row_count=100,
            after_row_count=100 - row_loss,
            row_delta=-row_loss,
            dropped_columns=["email"] if dropped_cols else [],
            type_changes={"amount": ("bigint", "integer")} if type_changes else {},
        ))
    return DiffResult(
        tables=tables,
        risk_level=risk,
        risk_reasons=reasons or [],
        is_refactor_only=is_refactor,
        total_row_loss=row_loss,
        summary="test",
    )


# ─────────────────────────────────────────────────────────────

class TestDecisionEngine:

    # ── Otomatik Onay ────────────────────────────────────────

    def test_low_risk_passes(self):
        diff = make_diff(risk=RiskLevel.LOW)
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.PASS

    def test_refactor_only_passes(self):
        diff = make_diff(risk=RiskLevel.MEDIUM, is_refactor=True)
        decision, msg = decision_engine.decide(diff)
        assert decision == DecisionResult.PASS
        assert "refactor" in msg.lower()

    def test_medium_no_row_loss_no_schema_change_passes(self):
        diff = make_diff(risk=RiskLevel.MEDIUM, row_loss=0)
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.PASS

    # ── Manuel İnceleme ──────────────────────────────────────

    def test_medium_with_row_loss_needs_manual(self):
        diff = make_diff(risk=RiskLevel.MEDIUM, row_loss=5, reasons=["5 satır silindi"])
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.MANUAL_REVIEW

    def test_medium_with_dropped_column_needs_manual(self):
        diff = make_diff(risk=RiskLevel.MEDIUM, dropped_cols=True, reasons=["kolon silindi"])
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.MANUAL_REVIEW

    def test_high_risk_needs_manual(self):
        diff = make_diff(risk=RiskLevel.HIGH, reasons=["tip küçültme"])
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.MANUAL_REVIEW

    # ── Blok ─────────────────────────────────────────────────

    def test_critical_risk_is_blocked(self):
        diff = make_diff(risk=RiskLevel.CRITICAL, row_loss=90, reasons=["90 satır kaybı"])
        decision, _ = decision_engine.decide(diff)
        assert decision == DecisionResult.BLOCK

    def test_apply_error_blocks(self):
        diff = make_diff(risk=RiskLevel.LOW)
        decision, msg = decision_engine.decide(diff, apply_error="syntax error")
        assert decision == DecisionResult.BLOCK
        assert "syntax error" in msg

    # ── Açıklamalar dolu mu? ──────────────────────────────────

    def test_decision_has_explanation(self):
        diff = make_diff(risk=RiskLevel.HIGH, reasons=["test"])
        _, msg = decision_engine.decide(diff)
        assert len(msg) > 0

    def test_critical_block_message_contains_reasons(self):
        diff = make_diff(risk=RiskLevel.CRITICAL, reasons=["kolon drop edildi", "90 satır kayıp"])
        _, msg = decision_engine.decide(diff)
        assert "kolon drop edildi" in msg or "90 satır kayıp" in msg
