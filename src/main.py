"""
DB Guardian — Ana FastAPI Uygulaması.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

from src.audit.models import AuditLog
from src.audit.router import router as audit_router
from src.breakglass.router import router as breakglass_router
from src.config import settings
from src.core.migration_queue import migration_queue
from src.database import Base, SessionLocal, engine
from src.gateway.auth import authenticate_user, create_access_token
from src.gateway.router import router as gateway_router
from src.models.schemas import TokenResponse
from src.monitor.router import router as monitor_router

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

    yield  # Uygulama çalışıyor

    # Kapatma
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router'lar ─────────────────────────────────────────────────────────────

app.include_router(gateway_router)
app.include_router(audit_router)
app.include_router(breakglass_router)
app.include_router(monitor_router)


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


# ── Sağlık kontrolü ────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health():
    """Basit sağlık kontrolü — load balancer için."""
    return {"status": "ok", "service": "db-guardian", "version": "1.0.0-mvp"}
