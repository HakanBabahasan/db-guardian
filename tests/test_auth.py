"""
Auth & Günlük Parola Testleri — src/gateway/auth.py

Hiç HTTP/DB bağlantısı gerektirmez.
"""
import pytest
from datetime import datetime

from src.gateway.auth import (
    authenticate_user,
    create_access_token,
    decode_token,
    generate_daily_password,
    verify_daily_password,
)


# ─────────────────────────────────────────────────────────────
# 1. Kullanıcı kimlik doğrulama
# ─────────────────────────────────────────────────────────────

class TestAuthentication:

    def test_valid_credentials_returns_user(self):
        user = authenticate_user("dev1", "dev123")
        assert user is not None
        assert user["username"] == "dev1"
        assert user["role"] == "developer"

    def test_admin_credentials(self):
        user = authenticate_user("admin", "admin123")
        assert user is not None
        assert user["role"] == "admin"

    def test_manager_credentials(self):
        user = authenticate_user("manager1", "manager123")
        assert user is not None
        assert user["role"] == "manager"

    def test_wrong_password_returns_none(self):
        user = authenticate_user("dev1", "yanlis_sifre")
        assert user is None

    def test_nonexistent_user_returns_none(self):
        user = authenticate_user("yokboylee", "herhangi")
        assert user is None

    def test_empty_password_returns_none(self):
        user = authenticate_user("dev1", "")
        assert user is None


# ─────────────────────────────────────────────────────────────
# 2. JWT Token
# ─────────────────────────────────────────────────────────────

class TestJWT:

    def test_create_and_decode_token(self):
        token = create_access_token({"sub": "dev1", "role": "developer"})
        payload = decode_token(token)
        assert payload["sub"] == "dev1"
        assert payload["role"] == "developer"

    def test_token_has_expiry(self):
        token = create_access_token({"sub": "dev1"})
        payload = decode_token(token)
        assert "exp" in payload

    def test_invalid_token_raises(self):
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_token("bu.gecersiz.bir.token")

    def test_tampered_token_raises(self):
        from jose import JWTError
        token = create_access_token({"sub": "dev1"})
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_different_users_get_different_tokens(self):
        t1 = create_access_token({"sub": "dev1"})
        t2 = create_access_token({"sub": "dev2"})
        assert t1 != t2


# ─────────────────────────────────────────────────────────────
# 3. Günlük Değişen Parola
# ─────────────────────────────────────────────────────────────

class TestDailyPassword:

    def test_password_generated_for_manager(self):
        pwd = generate_daily_password("manager1")
        assert isinstance(pwd, str)
        assert len(pwd) == 10
        assert pwd.isupper() or pwd.isalnum()

    def test_password_is_uppercase_alphanumeric(self):
        pwd = generate_daily_password("manager1")
        assert pwd == pwd.upper()

    def test_same_user_same_day_same_password(self):
        today = datetime(2026, 3, 1)
        p1 = generate_daily_password("manager1", date=today)
        p2 = generate_daily_password("manager1", date=today)
        assert p1 == p2

    def test_different_day_different_password(self):
        day1 = datetime(2026, 3, 1)
        day2 = datetime(2026, 3, 2)
        p1 = generate_daily_password("manager1", date=day1)
        p2 = generate_daily_password("manager1", date=day2)
        assert p1 != p2

    def test_different_managers_different_passwords(self):
        today = datetime(2026, 3, 1)
        p1 = generate_daily_password("manager1", date=today)
        p2 = generate_daily_password("manager2", date=today)
        assert p1 != p2

    def test_verify_correct_password_returns_true(self):
        today = datetime(2026, 3, 1)
        pwd = generate_daily_password("manager1", date=today)
        assert verify_daily_password("manager1", pwd, date=today) is True

    def test_verify_wrong_password_returns_false(self):
        today = datetime(2026, 3, 1)
        assert verify_daily_password("manager1", "YANLISGIRSE", date=today) is False

    def test_verify_yesterday_password_fails_today(self):
        yesterday = datetime(2026, 2, 28)
        today = datetime(2026, 3, 1)
        yesterday_pwd = generate_daily_password("manager1", date=yesterday)
        assert verify_daily_password("manager1", yesterday_pwd, date=today) is False

    def test_non_manager_raises(self):
        with pytest.raises(ValueError, match="yönetici değil"):
            generate_daily_password("dev1")

    def test_nonexistent_user_raises(self):
        with pytest.raises(ValueError, match="bulunamadı"):
            generate_daily_password("yokuseryok")
