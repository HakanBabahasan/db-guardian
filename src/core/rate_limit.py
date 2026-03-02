"""
DB Guardian — Rate Limiting Middleware.

Aynı kullanıcının /api/execute endpoint'ine dakikada en fazla
RATE_LIMIT_PER_MINUTE istek göndermesine izin verir.
JWT'den kullanıcı adı alınamazsa IP adresi kullanılır.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter."""

    def __init__(self, app, calls: int | None = None, period: int = 60):
        super().__init__(app)
        self.calls = calls or settings.rate_limit_per_minute
        self.period = period                         # saniye
        self._windows: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Yalnızca /api/execute sınırlandırılır
        if request.url.path != "/api/execute":
            return await call_next(request)

        key = self._get_key(request)
        now = time.monotonic()
        window = self._windows[key]

        # Süresi dolmuş girişleri temizle
        while window and window[0] <= now - self.period:
            window.popleft()

        if len(window) >= self.calls:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit aşıldı. Dakikada en fazla {self.calls} istek "
                        f"gönderilebilir. {self.period - (now - window[0]):.0f}s sonra tekrar deneyin."
                    )
                },
            )

        window.append(now)
        return await call_next(request)

    @staticmethod
    def _get_key(request: Request) -> str:
        """JWT varsa username, yoksa IP adresi."""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from jose import jwt as _jwt
                token = auth.split(" ", 1)[1]
                payload = _jwt.decode(
                    token, settings.jwt_secret_key,
                    algorithms=[settings.jwt_algorithm],
                    options={"verify_exp": False},
                )
                return f"user:{payload.get('sub', 'unknown')}"
            except Exception:
                pass
        # Fallback: IP
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"
