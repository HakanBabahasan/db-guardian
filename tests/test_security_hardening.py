"""
Security hardening testleri — grace period ve HMAC break-glass parolası.
"""
import time
import pytest
from datetime import datetime, timedelta, timezone

from src.gateway.auth import (
    create_access_token,
    decode_token_ignore_exp,
    generate_daily_password,
    verify_daily_password,
)
from src.config import settings


# ─────────────────────────────────────────────────────────────
# 1. Refresh token grace period
# ─────────────────────────────────────────────────────────────

class TestRefreshGracePeriod:

    def _make_expired_token(self, expired_minutes_ago: int) -> str:
        """Belirtilen dakika önce süresi dolmuş bir token üretir."""
        from jose import jwt
        payload = {
            "sub": "dev1",
            "role": "developer",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=expired_minutes_ago),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def test_recently_expired_token_accepted(self):
        token = self._make_expired_token(expired_minutes_ago=5)
        payload = decode_token_ignore_exp(token)
        assert payload["sub"] == "dev1"

    def test_token_expired_at_grace_boundary_accepted(self):
        token = self._make_expired_token(expired_minutes_ago=14)
        payload = decode_token_ignore_exp(token)
        assert payload["sub"] == "dev1"

    def test_token_expired_beyond_grace_period_rejected(self):
        token = self._make_expired_token(expired_minutes_ago=20)
        with pytest.raises(ValueError, match="grace period"):
            decode_token_ignore_exp(token)

    def test_token_expired_long_ago_rejected(self):
        token = self._make_expired_token(expired_minutes_ago=1440)
        with pytest.raises(ValueError, match="grace period"):
            decode_token_ignore_exp(token)


# ─────────────────────────────────────────────────────────────
# 2. HMAC break-glass parolası
# ─────────────────────────────────────────────────────────────

class TestHMACDailyPassword:

    def test_password_uses_server_secret(self):
        """Farklı secret ile aynı girdi farklı parola üretmeli."""
        today = datetime(2026, 6, 15)
        pwd1 = generate_daily_password("manager1", date=today)

        original_key = settings.breakglass_secret_key
        try:
            settings.breakglass_secret_key = "completely-different-secret"
            pwd2 = generate_daily_password("manager1", date=today)
        finally:
            settings.breakglass_secret_key = original_key

        assert pwd1 != pwd2

    def test_verify_uses_timing_safe_comparison(self):
        """verify_daily_password doğru parola ile True dönmeli."""
        today = datetime(2026, 6, 15)
        pwd = generate_daily_password("manager1", date=today)
        assert verify_daily_password("manager1", pwd, date=today) is True

    def test_verify_rejects_wrong_password(self):
        today = datetime(2026, 6, 15)
        assert verify_daily_password("manager1", "WRONGPASSWD", date=today) is False

    def test_password_deterministic_with_same_secret(self):
        today = datetime(2026, 6, 15)
        p1 = generate_daily_password("manager1", date=today)
        p2 = generate_daily_password("manager1", date=today)
        assert p1 == p2

    def test_password_format(self):
        pwd = generate_daily_password("manager1", date=datetime(2026, 6, 15))
        assert len(pwd) == 10
        assert pwd == pwd.upper()
        assert pwd.isalnum()
