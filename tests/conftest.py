"""
conftest.py — Test ortamını hazırlar.

.env dosyası olmadan da çalışması için environment variable'ları
burada mock olarak ayarlıyoruz.
"""
import os
import sys

# Proje kökünü Python path'e ekle (src.xxx importları için)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# .env olmadan çalışması için temel env değişkenleri
os.environ.setdefault("PROD_DB_HOST", "localhost")
os.environ.setdefault("PROD_DB_PORT", "5432")
os.environ.setdefault("PROD_DB_NAME", "guardian_prod")
os.environ.setdefault("PROD_DB_USER", "guardian")
os.environ.setdefault("PROD_DB_PASSWORD", "guardian_secret")
os.environ.setdefault("CLONE_DB_HOST", "localhost")
os.environ.setdefault("CLONE_DB_PORT", "5432")
os.environ.setdefault("CLONE_DB_NAME", "guardian_clone")
os.environ.setdefault("CLONE_DB_USER", "guardian")
os.environ.setdefault("CLONE_DB_PASSWORD", "guardian_secret")
os.environ.setdefault("APP_DB_HOST", "localhost")
os.environ.setdefault("APP_DB_PORT", "5432")
os.environ.setdefault("APP_DB_NAME", "guardian_app")
os.environ.setdefault("APP_DB_USER", "guardian")
os.environ.setdefault("APP_DB_PASSWORD", "guardian_secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREAKGLASS_TIMEOUT_SECONDS", "10")
os.environ.setdefault("BACKUP_DIR", "/tmp/guardian_backups")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
