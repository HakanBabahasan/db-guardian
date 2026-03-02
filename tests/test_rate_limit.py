"""
Rate Limit Testleri — src/core/rate_limit.py

Gerçek HTTP sunucusu gerektirmez; middleware mantığını doğrudan test eder.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_middleware(calls: int = 5) -> "RateLimitMiddleware":
    """Küçük limit ile test edilebilir bir middleware örneği döner."""
    from src.core.rate_limit import RateLimitMiddleware
    app_mock = MagicMock()
    mw = RateLimitMiddleware(app_mock, calls=calls)
    return mw


def _make_request(path: str = "/api/execute", auth: str = "") -> MagicMock:
    req = MagicMock()
    req.url.path = path
    req.headers = {"authorization": auth} if auth else {}
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    return req


async def _call_n_times(mw, req, n: int):
    """Aynı isteği n kez gönderir, son yanıt kodunu döner."""
    last_response = None
    for _ in range(n):
        next_mock = AsyncMock(return_value=MagicMock(status_code=200))
        last_response = await mw.dispatch(req, next_mock)
    return last_response


# ─────────────────────────────────────────────────────────────
# 1. Diğer path'ler kısıtlanmaz
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_execute_path_not_rate_limited():
    mw = _make_middleware(calls=2)
    req = _make_request(path="/auth/token")
    # 10 kez çağırılsa da 429 dönmemeli
    for _ in range(10):
        next_mock = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, next_mock)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# 2. Limit aşılınca 429 döner
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit():
    mw = _make_middleware(calls=3)
    req = _make_request(path="/api/execute")

    for i in range(3):
        next_mock = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, next_mock)
        assert resp.status_code == 200, f"{i+1}. istek 200 dönmeli"

    # 4. istek sınırı aşmalı
    next_mock = AsyncMock(return_value=MagicMock(status_code=200))
    resp = await mw.dispatch(req, next_mock)
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_response_contains_detail():
    mw = _make_middleware(calls=1)
    req = _make_request(path="/api/execute")

    await mw.dispatch(req, AsyncMock(return_value=MagicMock(status_code=200)))
    resp = await mw.dispatch(req, AsyncMock(return_value=MagicMock(status_code=200)))

    assert resp.status_code == 429
    body = resp.body
    assert b"Rate limit" in body or b"rate" in body.lower()


# ─────────────────────────────────────────────────────────────
# 3. Sliding window — eski istekler süreden sonra temizlenir
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sliding_window_resets_after_period():
    mw = _make_middleware(calls=2)
    mw.period = 1  # 1 saniyelik pencere
    req = _make_request(path="/api/execute")

    # 2 istek gönder (limit dolu)
    for _ in range(2):
        await mw.dispatch(req, AsyncMock(return_value=MagicMock(status_code=200)))

    # Pencere doluyken 429 beklenir
    resp = await mw.dispatch(req, AsyncMock(return_value=MagicMock(status_code=200)))
    assert resp.status_code == 429

    # 1 saniye bekle — pencere sıfırlanmalı
    time.sleep(1.05)
    resp = await mw.dispatch(req, AsyncMock(return_value=MagicMock(status_code=200)))
    assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# 4. _get_key — JWT ve IP anahtar mantığı
# ─────────────────────────────────────────────────────────────

def test_get_key_uses_ip_without_auth():
    from src.core.rate_limit import RateLimitMiddleware
    req = _make_request(path="/api/execute")
    key = RateLimitMiddleware._get_key(req)
    assert key.startswith("ip:")


def test_get_key_returns_ip_for_invalid_token():
    from src.core.rate_limit import RateLimitMiddleware
    req = _make_request(path="/api/execute", auth="Bearer not.a.valid.jwt")
    key = RateLimitMiddleware._get_key(req)
    assert key.startswith("ip:")


def test_get_key_extracts_username_from_valid_jwt():
    from src.gateway.auth import create_access_token
    from src.core.rate_limit import RateLimitMiddleware

    token = create_access_token({"sub": "dev1", "role": "developer"})
    req = _make_request(path="/api/execute", auth=f"Bearer {token}")
    key = RateLimitMiddleware._get_key(req)
    assert key == "user:dev1"


# ─────────────────────────────────────────────────────────────
# 5. Farklı kullanıcılar bağımsız pencerelere sahip
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_different_users_have_independent_windows():
    from src.gateway.auth import create_access_token
    mw = _make_middleware(calls=2)

    token_a = create_access_token({"sub": "dev1", "role": "developer"})
    token_b = create_access_token({"sub": "dev2", "role": "developer"})

    req_a = _make_request(path="/api/execute", auth=f"Bearer {token_a}")
    req_b = _make_request(path="/api/execute", auth=f"Bearer {token_b}")

    # dev1 limitini doldur
    for _ in range(2):
        await mw.dispatch(req_a, AsyncMock(return_value=MagicMock(status_code=200)))

    # dev1 için 429 beklenir
    resp_a = await mw.dispatch(req_a, AsyncMock(return_value=MagicMock(status_code=200)))
    assert resp_a.status_code == 429

    # dev2 henüz sınırını doldurmamış — 200 beklenir
    resp_b = await mw.dispatch(req_b, AsyncMock(return_value=MagicMock(status_code=200)))
    assert resp_b.status_code == 200
