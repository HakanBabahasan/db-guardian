"""
DB Guardian — Ana FastAPI Uygulaması.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from src.audit.models import AuditLog
from src.audit.router import router as audit_router
from src.breakglass.router import router as breakglass_router
from src.config import settings
from src.core.backup import backup_engine
from src.core.migration_queue import migration_queue
from src.core.rate_limit import RateLimitMiddleware
from src.database import Base, SessionLocal, engine
from src.gateway.auth import authenticate_user, create_access_token, decode_token_ignore_exp
from src.gateway.router import router as gateway_router
from src.models.schemas import TokenResponse
from src.monitor.router import router as monitor_router
from src.notifications.router import router as notifications_router
from src.rollback.router import router as rollback_router

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("guardian")


# ── Uygulama yaşam döngüsü ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Başlangıç ve kapatma işlemleri."""
    logger.info("DB Guardian başlatılıyor...")

    # Tabloları oluştur
    Base.metadata.create_all(bind=engine)
    logger.info("Veritabanı tabloları hazır.")

    # Migration kuyruğunu başlat
    migration_queue.start()
    logger.info("Migration kuyruğu aktif.")

    # Günlük backup temizleme görevi
    async def _daily_cleanup_task():
        import asyncio as _asyncio
        while True:
            await _asyncio.sleep(24 * 60 * 60)  # 24 saat bekle
            try:
                backup_engine.cleanup_old_backups()
                logger.info("Eski backup dosyaları temizlendi.")
            except Exception as exc:
                logger.warning(f"Backup temizleme hatası: {exc}")

    import asyncio as _asyncio
    cleanup_task = _asyncio.create_task(_daily_cleanup_task())

    yield  # Uygulama çalışıyor

    # Kapatma
    cleanup_task.cancel()
    migration_queue.stop()
    logger.info("DB Guardian kapatıldı.")


# ── FastAPI uygulaması ──────────────────────────────────────────────────────

app = FastAPI(
    title="DB Guardian",
    description=(
        "Production veritabanlarına giden her değişikliği yakalayan, "
        "klonlayan, test eden ve analiz eden güvenlik katmanı."
    ),
    version="1.0.0-mvp",
    lifespan=lifespan,
)

_cors_origins = (
    settings.allowed_origins.split(",")
    if settings.allowed_origins and settings.allowed_origins != "*"
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

# ── Prometheus metrik enstrümantasyonu ─────────────────────────────────────

try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["Monitoring"])
    logging.getLogger("guardian").info("Prometheus /metrics aktif.")
except ImportError:
    logging.getLogger("guardian").warning("prometheus-fastapi-instrumentator yüklü değil, /metrics devre dışı.")

# ── Router'lar ─────────────────────────────────────────────────────────────

app.include_router(gateway_router)
app.include_router(audit_router)
app.include_router(breakglass_router)
app.include_router(monitor_router)
app.include_router(rollback_router)
app.include_router(notifications_router)

# ── Frontend ───────────────────────────────────────────────────────────────

_frontend_dir = Path(__file__).parent.parent / "frontend"
if _frontend_dir.exists():
    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(str(_frontend_dir / "index.html"))


# ── Auth endpoint ──────────────────────────────────────────────────────────

@app.post("/auth/token", response_model=TokenResponse, tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    JWT token al.

    Demo kullanıcılar:
      admin / admin123
      manager1 / manager123
      manager2 / manager456
      dev1 / dev123
      dev2 / dev456
    """
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya parola hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return TokenResponse(access_token=token)


@app.post("/auth/refresh", response_model=TokenResponse, tags=["Auth"])
def refresh_token(current_token: str = Depends(OAuth2PasswordBearer(tokenUrl="/auth/token"))):
    """
    Geçerli (veya az önce dolmuş) token'dan yeni bir JWT alır.
    Token imzası doğrulanır, süre kontrolü atlanır.
    """
    try:
        payload = decode_token_ignore_exp(current_token)
        username = payload.get("sub")
        role = payload.get("role")
        if not username or not role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token.")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token doğrulaması başarısız.")
    new_token = create_access_token({"sub": username, "role": role})
    return TokenResponse(access_token=new_token)


# ── Sağlık kontrolü ────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health():
    """Basit sağlık kontrolü — load balancer için."""
    return {"status": "ok", "service": "db-guardian", "version": "1.0.0-mvp"}
