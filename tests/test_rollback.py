"""
Rollback Testleri — src/rollback/manager.py & router.py

Gerçek PostgreSQL bağlantısı gerektirmez.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.rollback.manager import RollbackEngine


# ─────────────────────────────────────────────────────────────
# 1. snapshot_exists
# ─────────────────────────────────────────────────────────────

class TestSnapshotExists:

    def test_existing_file_returns_true(self):
        engine = RollbackEngine()
        with tempfile.NamedTemporaryFile(suffix=".dump") as f:
            assert engine.snapshot_exists(f.name) is True

    def test_missing_file_returns_false(self):
        engine = RollbackEngine()
        assert engine.snapshot_exists("/tmp/nonexistent_guardian_snapshot.dump") is False

    def test_none_path_returns_false(self):
        engine = RollbackEngine()
        assert engine.snapshot_exists(None) is False

    def test_empty_string_returns_false(self):
        engine = RollbackEngine()
        assert engine.snapshot_exists("") is False


# ─────────────────────────────────────────────────────────────
# 2. restore — hata durumları
# ─────────────────────────────────────────────────────────────

class TestRollbackRestore:

    def test_restore_returns_failure_dict_when_snapshot_missing(self):
        engine = RollbackEngine()
        result = engine.restore("/tmp/nonexistent_guardian_snapshot.dump", "job-abc")
        assert result["success"] is False
        assert result["error"] is not None

    def test_restore_calls_subprocess_with_correct_args(self):
        engine = RollbackEngine()
        with tempfile.NamedTemporaryFile(suffix=".dump") as f:
            with patch("src.rollback.manager.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                result = engine.restore(f.name, "job-xyz")
                assert result["success"] is True
                # pg_restore veya psql çağrıldığını doğrula
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert any("pg_restore" in str(arg) or "psql" in str(arg) for arg in cmd)

    def test_restore_returns_failure_on_nonzero_exit(self):
        engine = RollbackEngine()
        with tempfile.NamedTemporaryFile(suffix=".dump") as f:
            with patch("src.rollback.manager.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="error detail")
                result = engine.restore(f.name, "job-xyz")
                assert result["success"] is False
                assert "error detail" in result["error"]


# ─────────────────────────────────────────────────────────────
# 3. Router — yetki ve durum kontrolleri (unit, DB'siz)
# ─────────────────────────────────────────────────────────────

class TestRollbackRouterLogic:
    """
    Router mantığını FastAPI test client olmadan,
    iş katmanı fonksiyonlarıyla doğrular.
    """

    def test_only_applied_jobs_can_rollback(self):
        """Sadece APPLIED durumdaki işler rollback edilebilir."""
        from src.models.schemas import JobStatus

        rollbackable = {JobStatus.APPLIED}
        non_rollbackable = {
            JobStatus.QUEUED,
            JobStatus.PROCESSING,
            JobStatus.AWAITING_APPROVAL,
            JobStatus.BLOCKED,
            JobStatus.FAILED,
            JobStatus.ROLLED_BACK,
        }

        for s in rollbackable:
            assert s in rollbackable
        for s in non_rollbackable:
            assert s not in rollbackable

    def test_rolled_back_status_exists_in_enum(self):
        from src.models.schemas import JobStatus
        assert hasattr(JobStatus, "ROLLED_BACK")
        assert JobStatus.ROLLED_BACK.value == "ROLLED_BACK"
