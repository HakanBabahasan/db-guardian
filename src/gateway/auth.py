"""
DB Guardian — JWT Kimlik Doğrulama & Yetkilendirme.

Kullanıcı rolleri:
  developer  → SQL gönderme, iş durumu sorgulama
  manager    → Break-glass onaylama, audit log okuma
  admin      → Tüm yetkiler
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import settings

logger = logging.getLogger("guardian.auth")

# ── Şifreleme ────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# ── Demo kullanıcı veritabanı ────────────────────────────────────────────────
# Yalnızca APP_ENV=development modunda yüklenir.
# Production'da kullanıcılar harici bir kaynaktan (DB, LDAP vb.) gelmelidir.

_DEMO_USERS = {
    "admin": {
        "hashed_password": pwd_context.hash("admin123"),
        "role": "admin",
        "full_name": "System Admin",
        "birth_date": 15,
        "birth_year": 1985,
    },
    "manager1": {
        "hashed_password": pwd_context.hash("manager123"),
        "role": "manager",
        "full_name": "Ali Yilmaz",
        "birth_date": 7,
        "birth_year": 1988,
    },
    "manager2": {
        "hashed_password": pwd_context.hash("manager456"),
        "role": "manager",
        "full_name": "Ayse Kaya",
        "birth_date": 22,
        "birth_year": 1990,
    },
    "dev1": {
        "hashed_password": pwd_context.hash("dev123"),
        "role": "developer",
        "full_name": "Mehmet Demir",
        "birth_date": 3,
        "birth_year": 1995,
    },
    "dev2": {
        "hashed_password": pwd_context.hash("dev456"),
        "role": "developer",
        "full_name": "Zeynep Celik",
        "birth_date": 28,
        "birth_year": 1997,
    },
}

_USERS: dict = _DEMO_USERS if settings.app_env != "production" else {}

if settings.app_env != "production":
    logger.info("Demo kullanıcılar yüklendi (development modu).")
else:
    logger.warning("Production modu — demo kullanıcılar devre dışı.")


# ── Token işlemleri ──────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload["exp"] = expire
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# ── Kullanıcı doğrulama ──────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> dict | None:
    user = _USERS.get(username)
    if not user:
        return None
    if not pwd_context.verify(password, user["hashed_password"]):
        return None
    return {"username": username, **user}


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    """FastAPI bağımlılığı — mevcut kullanıcıyı döner."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Geçersiz veya süresi dolmuş token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        username: str = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = _USERS.get(username)
    if not user:
        raise credentials_exception
    return {"username": username, **user}


def require_role(*roles: str):
    """
    Belirtilen rollere sahip kullanıcıya izin verir.

    Kullanım:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
    """
    def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu işlem için gereken rol: {roles}. Mevcut rol: {current_user['role']}",
            )
        return current_user
    return _check


# ── Günlük değişen parola ──────────────────────────────────────────────────

def generate_daily_password(username: str, date: datetime | None = None) -> str:
    """
    Yönetici için günlük değişen parola üretir.

    Algoritma:
      - Kişisel bilgiler (isim + doğum günü + doğum yılı) + tarih (YYYYMMDD)
      - SHA-256 hash'inin ilk 10 karakteri → büyük harfe çevirilen parola
    """
    user = _USERS.get(username)
    if not user:
        raise ValueError(f"Kullanıcı bulunamadı: {username}")
    if user["role"] not in ("manager", "admin"):
        raise ValueError(f"{username} yönetici değil.")

    if date is None:
        date = datetime.now(timezone.utc)

    date_str = date.strftime("%Y%m%d")
    raw = (
        f"{username}"
        f"{user['full_name'].replace(' ', '').lower()}"
        f"{user['birth_date']}"
        f"{user['birth_year']}"
        f"{date_str}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return digest[:10].upper()


def verify_daily_password(username: str, provided: str, date: datetime | None = None) -> bool:
    """Verilen parolayı bugünün beklenen parolasıyla karşılaştırır."""
    expected = generate_daily_password(username, date)
    return provided == expected

def decode_token_ignore_exp(token: str) -> dict:
    """
    Token'ı imza açısından doğrular, süre dolmuşluk kontrolünü atlar.
    SADECE refresh akışına özgeli kullanılır.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": False},
    )