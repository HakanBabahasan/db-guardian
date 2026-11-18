"""
DB Guardian — Merkezi konfigürasyon.
Tüm ayarlar .env dosyasından ya da environment variables'tan okunur.
"""
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Production DB ───────────────────────────────────────
    prod_db_host: str = Field(default="prod_db", alias="PROD_DB_HOST")
    prod_db_port: int = Field(default=5432, alias="PROD_DB_PORT")
    prod_db_name: str = Field(default="guardian_prod", alias="PROD_DB_NAME")
    prod_db_user: str = Field(default="guardian", alias="PROD_DB_USER")
    prod_db_password: str = Field(default="guardian_secret", alias="PROD_DB_PASSWORD")

    # ── Clone DB ────────────────────────────────────────────
    clone_db_host: str = Field(default="clone_db", alias="CLONE_DB_HOST")
    clone_db_port: int = Field(default=5432, alias="CLONE_DB_PORT")
    clone_db_name: str = Field(default="guardian_clone", alias="CLONE_DB_NAME")
    clone_db_user: str = Field(default="guardian", alias="CLONE_DB_USER")
    clone_db_password: str = Field(default="guardian_secret", alias="CLONE_DB_PASSWORD")

    # ── Uygulama DB ─────────────────────────────────────────
    app_db_host: str = Field(default="app_db", alias="APP_DB_HOST")
    app_db_port: int = Field(default=5432, alias="APP_DB_PORT")
    app_db_name: str = Field(default="guardian_app", alias="APP_DB_NAME")
    app_db_user: str = Field(default="guardian", alias="APP_DB_USER")
    app_db_password: str = Field(default="guardian_secret", alias="APP_DB_PASSWORD")

    # ── JWT ─────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default="change-this-super-secret-key-in-production", alias="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    # ── Break-Glass ─────────────────────────────────────────
    breakglass_timeout_seconds: int = Field(default=900, alias="BREAKGLASS_TIMEOUT_SECONDS")
    breakglass_secret_key: str = Field(
        default="change-this-breakglass-secret-in-production", alias="BREAKGLASS_SECRET_KEY"
    )
    maintenance_max_hours: int = Field(default=24, alias="MAINTENANCE_MAX_HOURS")

    # ── Backup ──────────────────────────────────────────────
    backup_dir: str = Field(default="/backups", alias="BACKUP_DIR")
    backup_retention_days: int = Field(default=7, alias="BACKUP_RETENTION_DAYS")

    # ── Genel ───────────────────────────────────────────────
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── Bildirimler — Slack ──────────────────────────────────
    slack_webhook_url: str | None = Field(default=None, alias="SLACK_WEBHOOK_URL")

    # ── Bildirimler — SMTP ───────────────────────────────────
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="guardian@guardian.local", alias="SMTP_FROM")
    smtp_to: str | None = Field(default=None, alias="SMTP_TO")

    # ── Rate Limiting ────────────────────────────────────────
    rate_limit_per_minute: int = Field(default=10, alias="RATE_LIMIT_PER_MINUTE")

    # ── CORS ─────────────────────────────────────────────────
    # Production'da virgülle ayrılmış izin verilen origin listesi.
    # Örn: "https://guardian.company.com,https://admin.company.com"
    # Boş veya "*" bırakılırsa tüm originlere izin verilir (yalnızca dev).
    allowed_origins: str = Field(default="http://localhost:3000", alias="ALLOWED_ORIGINS")

    # ──────────────────────────────────────────────────────────
    @property
    def prod_dsn(self) -> str:
        return (
            f"postgresql://{self.prod_db_user}:{self.prod_db_password}"
            f"@{self.prod_db_host}:{self.prod_db_port}/{self.prod_db_name}"
        )

    @property
    def clone_dsn(self) -> str:
        return (
            f"postgresql://{self.clone_db_user}:{self.clone_db_password}"
            f"@{self.clone_db_host}:{self.clone_db_port}/{self.clone_db_name}"
        )

    @property
    def app_dsn(self) -> str:
        return (
            f"postgresql://{self.app_db_user}:{self.app_db_password}"
            f"@{self.app_db_host}:{self.app_db_port}/{self.app_db_name}"
        )

    model_config = ConfigDict(env_file=".env", populate_by_name=True)


settings = Settings()
