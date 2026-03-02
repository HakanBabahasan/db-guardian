"""
Tam Pipeline Entegrasyon Testi (mock DB)

DB bağlantısı olmadan DiffAnaliz → KararMotoru zincirini baştan sona test eder.
Gerçek clone/backup yerine mock kullanır.

Temel ilke: karar tamamen gerçek diff'e dayanır — SQL metnine, tahmine dayalı
kural eşleşmesine hiç bakılmaz. Sorgunun ne olduğundan bağımsız, klon üzerindeki
değişiklik ne ise o değerlendirilir.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.core.diff_analyzer import DiffAnalyzer
from src.core.decision_engine import DecisionEngine
from src.models.schemas import DecisionResult, RiskLevel


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def make_snap(table: str, rows: int, columns: dict | None = None) -> dict:
    return {"tables": {table: {"row_count": rows, "columns": columns or {"id": {"type": "integer", "nullable": False}}}}}


def run_pipeline(sql: str, prod_snap: dict, clone_snap: dict) -> tuple[str, str]:
    """
    Simüle edilmiş tam pipeline — saf diff tabanlı:
      1. Diff analizi: prod snapshot ile klon snapshot karşılaştırılır.
      2. Karar motoru: diff'e göre PASS / MANUAL_REVIEW / BLOCK üretir.
    SQL metni hiç okunmaz; karar tamamen gerçek diff sonucuna dayanır.
    Returns: (decision, message)
    """
    analyzer = DiffAnalyzer()
    diff = analyzer.analyze(prod_snap, clone_snap)

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
# Senaryo 2: Diff tabanlı tehlike tespiti
# ─────────────────────────────────────────────────────────────

class TestDiffBasedDetection:
    """
    Karar SQL metninden bağımsızdır — sadece diff sonucu belirler.

    Klon snapshot prod ile aynıysa (SQL DB'yi etkilemedi) → PASS.
    Klon snapshot değiştiyse → diff'e göre MANUAL_REVIEW veya BLOCK.
    """

    def test_no_change_in_clone_passes(self):
        """Herhangi bir SQL — klonda değişiklik yok → PASS."""
        prod = make_snap("payments", 500)
        decision, msg = run_pipeline("DELETE FROM payments", prod, prod)
        assert decision == DecisionResult.PASS

    def test_no_change_select_passes(self):
        """SELECT bile olsa, klonda değişiklik yok → PASS."""
        prod = make_snap("users", 1000)
        decision, msg = run_pipeline("SELECT * FROM users", prod, prod)
        assert decision == DecisionResult.PASS

    def test_drop_table_real_diff_blocked(self):
        """Klon snapshotı tablo silinmesini yansıtıyorsa → BLOCK."""
        prod = {"tables": {"payments": {"row_count": 500, "columns": {"id": {"type": "integer", "nullable": False}}}}}
        clone = {"tables": {}}  # tablo gerçekten silindi
        decision, msg = run_pipeline("DROP TABLE payments", prod, clone)
        assert decision == DecisionResult.BLOCK

    def test_full_row_loss_blocked(self):
        """Tüm satırlar silindi → BLOCK."""
        prod = make_snap("users", 1000)
        clone = make_snap("users", 0)
        decision, msg = run_pipeline("DELETE FROM users", prod, clone)
        assert decision == DecisionResult.BLOCK

    def test_truncate_real_diff_blocked(self):
        """TRUNCATE klonda tüm satırları sildi → BLOCK."""
        prod = make_snap("orders", 800)
        clone = make_snap("orders", 0)
        decision, msg = run_pipeline("TRUNCATE orders", prod, clone)
        assert decision == DecisionResult.BLOCK


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
