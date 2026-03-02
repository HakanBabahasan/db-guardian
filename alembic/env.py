"""
Alembic migration ortamı.
Bağlantı bilgisini src.config.settings'ten alır.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Proje kökünü sys.path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Base  # noqa: E402  (tüm model importları buradan)
from src.audit.models import AuditLog  # noqa: E402  model kayıt için import et
from src.config import settings  # noqa: E402

config = context.config

# Bağlantı URL'sini settings'ten override et
config.set_main_option("sqlalchemy.url", settings.app_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Veritabanı bağlantısı olmadan SQL üret."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Canlı veritabanı bağlantısıyla migrasyon çalıştır."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
