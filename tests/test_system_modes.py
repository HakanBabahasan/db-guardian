"""
Sistem Modu Testleri — src/monitor/modes.py
"""
import pytest
from src.monitor.modes import SystemModeManager
from src.models.schemas import SystemMode


@pytest.fixture
def mode_manager():
    return SystemModeManager()


class TestSystemModes:

    def test_starts_in_active_mode(self, mode_manager):
        assert mode_manager.mode == SystemMode.ACTIVE
        assert mode_manager.is_active is True

    def test_enter_maintenance(self, mode_manager):
        mode_manager.enter_maintenance("test bakımı")
        assert mode_manager.mode == SystemMode.MAINTENANCE
        assert mode_manager.is_maintenance is True
        assert mode_manager.is_active is False

    def test_enter_monitoring(self, mode_manager):
        mode_manager.enter_monitoring("izleme başladı")
        assert mode_manager.mode == SystemMode.MONITORING
        assert mode_manager.is_monitoring is True

    def test_resume_active_from_maintenance(self, mode_manager):
        mode_manager.enter_maintenance("bakım")
        mode_manager.resume_active("bakım bitti")
        assert mode_manager.mode == SystemMode.ACTIVE
        assert mode_manager.is_active is True

    def test_resume_active_from_monitoring(self, mode_manager):
        mode_manager.enter_monitoring("izleme")
        mode_manager.resume_active("izleme bitti")
        assert mode_manager.mode == SystemMode.ACTIVE

    def test_uptime_is_positive(self, mode_manager):
        import time
        time.sleep(0.01)
        assert mode_manager.uptime_seconds() > 0

    def test_status_info_returns_dict(self, mode_manager):
        info = mode_manager.status_info()
        assert "mode" in info
        assert "reason" in info
        assert "changed_at" in info

    def test_status_info_reflects_current_mode(self, mode_manager):
        mode_manager.enter_maintenance("test")
        info = mode_manager.status_info()
        assert info["mode"] == SystemMode.MAINTENANCE
        assert "test" in info["reason"]
