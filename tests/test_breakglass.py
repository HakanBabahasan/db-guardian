"""
Break-Glass Mekanizması Testleri — src/breakglass/manager.py

Hiç DB veya HTTP sunucusu gerektirmez.
"""
import asyncio
import pytest
from datetime import datetime, timezone

from src.breakglass.manager import BreakGlassManager
from src.gateway.auth import generate_daily_password
from src.models.schemas import BreakGlassStatus


@pytest.fixture
def manager():
    """Her test için temiz bir BreakGlassManager örneği."""
    return BreakGlassManager()


@pytest.fixture
def today():
    return datetime(2026, 3, 1)


@pytest.fixture
def manager1_pwd(today):
    return generate_daily_password("manager1", date=today)


@pytest.fixture
def manager2_pwd(today):
    return generate_daily_password("manager2", date=today)


# ─────────────────────────────────────────────────────────────
# 1. Talep oluşturma
# ─────────────────────────────────────────────────────────────

class TestBreakGlassRequest:

    def test_request_creates_session(self, manager):
        session = manager.request("job-001", "önemli bir değişiklik", "dev1")
        assert session is not None
        assert session.job_id == "job-001"
        assert session.status == BreakGlassStatus.PENDING

    def test_session_retrievable_by_job_id(self, manager):
        manager.request("job-002", "test", "dev1")
        session = manager.get_session("job-002")
        assert session is not None

    def test_nonexistent_session_returns_none(self, manager):
        assert manager.get_session("yok-olan-id") is None

    def test_session_has_expiry(self, manager):
        session = manager.request("job-003", "test", "dev1")
        assert session.expires_at is not None
        assert session.expires_at > datetime.now(timezone.utc)

    def test_approvals_initially_empty(self, manager):
        session = manager.request("job-004", "test", "dev1")
        assert session.approvals == []


# ─────────────────────────────────────────────────────────────
# 2. Onay akışı
# ─────────────────────────────────────────────────────────────

class TestBreakGlassApproval:

    def test_first_approval_is_partial(self, manager, today, manager1_pwd):
        manager.request("job-010", "test", "dev1")
        success, msg = manager.approve("job-010", "manager1", manager1_pwd)
        assert success is True
        session = manager.get_session("job-010")
        assert session.status == BreakGlassStatus.PARTIAL
        assert "manager1" in session.approvals

    def test_second_approval_completes(self, manager, today, manager1_pwd, manager2_pwd):
        manager.request("job-011", "test", "dev1")
        manager.approve("job-011", "manager1", manager1_pwd)
        success, msg = manager.approve("job-011", "manager2", manager2_pwd)
        assert success is True
        session = manager.get_session("job-011")
        assert session.status == BreakGlassStatus.APPROVED
        assert len(session.approvals) == 2

    def test_same_manager_cannot_approve_twice(self, manager, today, manager1_pwd):
        manager.request("job-012", "test", "dev1")
        manager.approve("job-012", "manager1", manager1_pwd)
        success, msg = manager.approve("job-012", "manager1", manager1_pwd)
        assert success is False
        assert "zaten onayladı" in msg

    def test_wrong_daily_password_fails(self, manager):
        manager.request("job-013", "test", "dev1")
        success, msg = manager.approve("job-013", "manager1", "YANLISP")
        assert success is False
        assert "parola" in msg.lower()

    def test_nonexistent_job_fails(self, manager, manager1_pwd):
        success, msg = manager.approve("yok-olan-job", "manager1", manager1_pwd)
        assert success is False
        assert "bulunamadı" in msg

    def test_approved_session_rejects_further_approval(
        self, manager, today, manager1_pwd, manager2_pwd
    ):
        manager.request("job-014", "test", "dev1")
        manager.approve("job-014", "manager1", manager1_pwd)
        manager.approve("job-014", "manager2", manager2_pwd)
        # Üçüncü kişi onaylamaya çalışıyor (admin gibi)
        admin_pwd = generate_daily_password("admin", date=today)
        success, msg = manager.approve("job-014", "admin", admin_pwd)
        assert success is False  # APPROVED durumda, kabul etmemeli


# ─────────────────────────────────────────────────────────────
# 3. Timeout
# ─────────────────────────────────────────────────────────────

class TestBreakGlassTimeout:

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self):
        """
        wait_for_approval 1 saniyelik iç timeout ile çağrılır.
        Onay verilmeden timeout dolunca False dönmeli.
        Outer asyncio.wait_for sarmalamıyoruz — Python 3.11+'de nested
        wait_for'lar CancelledError çakışmasına neden olabilir.
        """
        from src.breakglass.manager import BreakGlassManager, BreakGlassSession
        from src.models.schemas import BreakGlassStatus
        from datetime import timedelta, timezone

        session = BreakGlassSession(
            job_id="timeout-job",
            reason="test",
            requested_by="dev1",
        )
        session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=1)

        m = BreakGlassManager()
        m._sessions["timeout-job"] = session

        # Doğrudan çağır — iç timeout 1 sn sonra devreye girer
        result = await m.wait_for_approval("timeout-job")
        assert result is False
        assert session.status == BreakGlassStatus.EXPIRED
