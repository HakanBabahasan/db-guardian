"""
Tam Pipeline Entegrasyon Testi (mock DB)

DB bağlantısı olmadan KomutFiltresi → DiffAnaliz → KararMotoru zincirini
baştan sona test eder. Gerçek clone/backup yerine mock kullanır.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.core.command_filter import FilterDecision, check as filter_check
from src.core.diff_analyzer import DiffAnalyzer
from src.core.decision_engine import DecisionEngine
from src.models.schemas import DecisionResult, RiskLevel


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def make_snap(table: str, rows: int, columns: dict | None = None) -> dict:
    return {"tables": {table: {"row_count": rows, "columns": columns or {"id": {"type": "integer", "nullable": False}}}}}


def run_pipeline(sql: str, prod_snap: dict, clone_snap: dict) -> tuple[str, str]:
    """
    Simüle edilmiş tam pipeline.
    Returns: (decision, message)
    """
    # Aşama 1: Komut filtresi
    filter_result = filter_check(sql)
    if filter_result.decision == FilterDecision.INSTANT_BLOCK:
        return DecisionResult.INSTANT_BLOCK, filter_result.reason
    if filter_result.decision == FilterDecision.HIGH_RISK:
        # HIGH_RISK filtreden geçebilir ama diff analizi MANUAL_REVIEW döndürür
        pass

    # Aşama 2: Diff analizi (mock klon sonrası)
    analyzer = DiffAnalyzer()
    diff = analyzer.analyze(prod_snap, clone_snap)

    # Aşama 3: Karar
    engine = DecisionEngine()
    decision, msg = engine.decide(diff)
    return decision, msg


# ─────────────────────────────────────────────────────────────
# Senaryo 1: Güvenli değişiklik — kolon ekleme
# ─────────────────────────────────────────────────────────────

class TestSafeScenario:

    def test_add_column_passes_full_pipeline(self):
        sql = "ALTER TABLE users ADD COLUMN phone VARCHAR(20)"
        prod = make_snap("users", 100)
        clone = make_snap("users", 100, {
            "id":    {"type": "integer", "nullable": False},
            "phone": {"type": "character varying", "nullable": True},
        })
        decision, msg = run_pipeline(sql, prod, clone)
        assert decision == DecisionResult.PASS

    def test_new_index_passes(self):
        sql = "CREATE INDEX CONCURRENTLY idx_email ON users(email)"
        prod = make_snap("users", 200)
        decision, msg = run_pipeline(sql, prod, prod)  # aynı snapshot → değişiklik yok
        assert decision == DecisionResult.PASS


# ─────────────────────────────────────────────────────────────
# Senaryo 2: WHERE'siz DELETE — anında blok
# ─────────────────────────────────────────────────────────────

class TestInstantBlockScenario:

    def test_delete_without_where_instant_block(self):
        sql = "DELETE FROM payments"
        prod = make_snap("payments", 500)
        decision, msg = run_pipeline(sql, prod, prod)
        assert decision == DecisionResult.INSTANT_BLOCK

    def test_drop_table_instant_block(self):
        sql = "DROP TABLE payments"
        prod = make_snap("payments", 500)
        decision, msg = run_pipeline(sql, prod, prod)
        assert decision == DecisionResult.INSTANT_BLOCK

    def test_truncate_instant_block(self):
        decision, msg = run_pipeline("TRUNCATE users", make_snap("users", 100), make_snap("users", 100))
        assert decision == DecisionResult.INSTANT_BLOCK


# ─────────────────────────────────────────────────────────────
# Senaryo 3: Büyük veri kaybı — BLOCK
# ─────────────────────────────────────────────────────────────

class TestCriticalScenario:

    def test_massive_row_loss_is_blocked(self):
        """WHERE'li DELETE büyük veri kaybına yol açıyorsa BLOCK (diff motoru yakalar)"""
        sql = "DELETE FROM users WHERE created_at < '2020-01-01'"
        prod = make_snap("users", 1000)
        clone = make_snap("users", 10)  # %99 kayıp
        decision, msg = run_pipeline(sql, prod, clone)
        assert decision == DecisionResult.BLOCK

    def test_column_drop_is_blocked(self):
        sql = "ALTER TABLE users DROP COLUMN email"
        prod = make_snap("users", 100, {"id": {"type": "integer", "nullable": False}, "email": {"type": "text", "nullable": False}})
        clone = make_snap("users", 100, {"id": {"type": "integer", "nullable": False}})
        decision, msg = run_pipeline(sql, prod, clone)
        assert decision == DecisionResult.BLOCK


# ─────────────────────────────────────────────────────────────
# Senaryo 4: Orta risk — Manuel inceleme
# ─────────────────────────────────────────────────────────────

class TestManualReviewScenario:

    def test_moderate_row_loss_needs_manual_review(self):
        sql = "DELETE FROM sessions WHERE last_seen < '2025-01-01'"
        prod = make_snap("sessions", 1000)
        clone = make_snap("sessions", 850)  # %15 kayıp → MEDIUM/HIGH
        decision, msg = run_pipeline(sql, prod, clone)
        assert decision in (DecisionResult.MANUAL_REVIEW, DecisionResult.BLOCK)

    def test_type_shrink_needs_manual_review(self):
        sql = "ALTER TABLE payments ALTER COLUMN amount TYPE INTEGER"
        prod = make_snap("payments", 100, {
            "id":     {"type": "integer", "nullable": False},
            "amount": {"type": "bigint",  "nullable": False},
        })
        clone = make_snap("payments", 100, {
            "id":     {"type": "integer", "nullable": False},
            "amount": {"type": "integer", "nullable": False},
        })
        decision, msg = run_pipeline(sql, prod, clone)
        assert decision in (DecisionResult.MANUAL_REVIEW, DecisionResult.BLOCK)


# ─────────────────────────────────────────────────────────────
# Senaryo 5: Apply error → BLOCK
# ─────────────────────────────────────────────────────────────

class TestApplyError:

    def test_apply_error_always_blocks(self):
        """SQL klona uygulanamadığında karar motoru doğrudan BLOCK üretmeli."""
        from src.core.decision_engine import decision_engine
        from src.models.schemas import DiffResult
        diff = DiffResult(
            tables=[], risk_level=RiskLevel.LOW,
            risk_reasons=[], is_refactor_only=False,
            total_row_loss=0, summary="",
        )
        decision, msg = decision_engine.decide(diff, apply_error="column 'xyz' does not exist")
        assert decision == DecisionResult.BLOCK
        assert "xyz" in msg
