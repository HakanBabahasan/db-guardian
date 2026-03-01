"""
Diff Analiz Testi — src/core/diff_analyzer.py

Production snapshot ile klon snapshot karşılaştırması.
Hiç DB bağlantısı gerektirmez.
"""
import pytest
from src.core.diff_analyzer import DiffAnalyzer
from src.models.schemas import RiskLevel


# ── Yardımcı snapshot builder ─────────────────────────────────────────────

def make_snapshot(tables: dict) -> dict:
    """
    Kolaylaştırılmış snapshot oluşturucu.

    Örnek:
        make_snapshot({
            "users": {"row_count": 100, "columns": {
                "id":    {"type": "integer", "nullable": False},
                "email": {"type": "text",    "nullable": False},
            }}
        })
    """
    return {"tables": tables}


def col(type_: str, nullable: bool = False) -> dict:
    return {"type": type_, "nullable": nullable}


analyzer = DiffAnalyzer()


# ─────────────────────────────────────────────────────────────
# 1. Değişiklik yok
# ─────────────────────────────────────────────────────────────

class TestNoChange:

    def test_identical_snapshots_are_low_risk(self):
        snap = make_snapshot({
            "users": {"row_count": 50, "columns": {
                "id":    col("integer"),
                "email": col("text", nullable=True),
            }}
        })
        result = analyzer.analyze(snap, snap)
        assert result.risk_level == RiskLevel.LOW

    def test_identical_returns_no_row_loss(self):
        snap = make_snapshot({"payments": {"row_count": 200, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(snap, snap)
        assert result.total_row_loss == 0

    def test_only_ordering_change_detected_as_refactor(self):
        """Satır sayısı aynı, kolon yapısı aynı → refactor_only = True"""
        snap = make_snapshot({
            "users": {"row_count": 100, "columns": {"id": col("integer"), "name": col("text")}}
        })
        result = analyzer.analyze(snap, snap)
        assert result.is_refactor_only is True


# ─────────────────────────────────────────────────────────────
# 2. Satır kaybı senaryoları
# ─────────────────────────────────────────────────────────────

class TestRowLoss:

    def test_small_row_loss_is_medium(self):
        prod = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 95, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        assert result.total_row_loss == 5

    def test_large_row_loss_is_critical(self):
        """Production'da 100 satır, klonda 10 → %90 kayıp → CRITICAL"""
        prod = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 10, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.total_row_loss == 90

    def test_fifty_percent_row_loss_is_critical(self):
        prod = make_snapshot({"users": {"row_count": 200, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.CRITICAL

    def test_row_gain_is_low_risk(self):
        """Satır ekleme güvenlidir."""
        prod = make_snapshot({"users": {"row_count": 50, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 55, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.LOW
        assert result.total_row_loss == 0


# ─────────────────────────────────────────────────────────────
# 3. Kolon değişiklikleri
# ─────────────────────────────────────────────────────────────

class TestColumnChanges:

    def test_dropped_column_is_critical(self):
        prod = make_snapshot({"users": {"row_count": 50, "columns": {
            "id": col("integer"), "email": col("text"),
        }}})
        clone = make_snapshot({"users": {"row_count": 50, "columns": {
            "id": col("integer"),
            # email silindi
        }}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.CRITICAL

    def test_dropped_column_listed_in_diff(self):
        prod = make_snapshot({"users": {"row_count": 10, "columns": {
            "id": col("integer"), "email": col("text"),
        }}})
        clone = make_snapshot({"users": {"row_count": 10, "columns": {
            "id": col("integer"),
        }}})
        result = analyzer.analyze(prod, clone)
        assert any("email" in r for r in result.risk_reasons)

    def test_added_column_is_low_risk(self):
        prod = make_snapshot({"users": {"row_count": 20, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 20, "columns": {
            "id": col("integer"), "phone": col("text", nullable=True),
        }}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.LOW

    def test_type_shrink_is_high_risk(self):
        """bigint → integer: overflow riski"""
        prod = make_snapshot({"payments": {"row_count": 100, "columns": {
            "id": col("integer"), "amount": col("bigint"),
        }}})
        clone = make_snapshot({"payments": {"row_count": 100, "columns": {
            "id": col("integer"), "amount": col("integer"),
        }}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_type_expand_is_medium_risk(self):
        """integer → bigint: genişleme, daha az tehlikeli"""
        prod = make_snapshot({"payments": {"row_count": 100, "columns": {
            "id": col("integer"), "amount": col("integer"),
        }}})
        clone = make_snapshot({"payments": {"row_count": 100, "columns": {
            "id": col("integer"), "amount": col("bigint"),
        }}})
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.MEDIUM

    def test_nullable_change_tracked(self):
        """nullable False → True değişimi constraint değişikliği sayılır."""
        prod = make_snapshot({"users": {"row_count": 10, "columns": {
            "id": col("integer"), "email": col("text", nullable=False),
        }}})
        clone = make_snapshot({"users": {"row_count": 10, "columns": {
            "id": col("integer"), "email": col("text", nullable=True),
        }}})
        result = analyzer.analyze(prod, clone)
        tbl = result.tables[0]
        assert len(tbl.constraint_changes) > 0


# ─────────────────────────────────────────────────────────────
# 4. Yeni tablo ekleme
# ─────────────────────────────────────────────────────────────

class TestNewTable:

    def test_new_table_added_is_low_risk(self):
        prod = make_snapshot({"users": {"row_count": 10, "columns": {"id": col("integer")}}})
        clone = make_snapshot({
            "users":     {"row_count": 10, "columns": {"id": col("integer")}},
            "new_table": {"row_count": 0,  "columns": {"id": col("integer")}},
        })
        result = analyzer.analyze(prod, clone)
        assert result.risk_level == RiskLevel.LOW


# ─────────────────────────────────────────────────────────────
# 5. Risk reasons ve summary dolu mu?
# ─────────────────────────────────────────────────────────────

class TestOutputFormat:

    def test_critical_risk_has_reasons(self):
        prod = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 5, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert len(result.risk_reasons) > 0

    def test_summary_not_empty_on_change(self):
        prod = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 5, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.summary != ""

    def test_table_diff_delta_correct(self):
        prod = make_snapshot({"users": {"row_count": 100, "columns": {"id": col("integer")}}})
        clone = make_snapshot({"users": {"row_count": 80, "columns": {"id": col("integer")}}})
        result = analyzer.analyze(prod, clone)
        assert result.tables[0].row_delta == -20
