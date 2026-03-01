"""
DB Guardian — Clone Engine.

Production DB'nin anlık bir kopyasını oluşturur.
Strateji: pg_dump → pg_restore (en güvenilir yol).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime

import psycopg2

from src.config import settings

logger = logging.getLogger("guardian.clone")


class CloneEngine:
    """Production veritabanının izole kopyasını oluşturur ve yönetir."""

    def __init__(self):
        self._env = {
            **os.environ,
            "PGPASSWORD": settings.clone_db_password,
        }
        self._prod_env = {
            **os.environ,
            "PGPASSWORD": settings.prod_db_password,
        }

    # ── Yardımcı bağlantılar ─────────────────────────────────────────────

    def _prod_conn(self):
        return psycopg2.connect(
            host=settings.prod_db_host,
            port=settings.prod_db_port,
            dbname=settings.prod_db_name,
            user=settings.prod_db_user,
            password=settings.prod_db_password,
        )

    def _clone_conn(self, dbname: str | None = None):
        return psycopg2.connect(
            host=settings.clone_db_host,
            port=settings.clone_db_port,
            dbname=dbname or settings.clone_db_name,
            user=settings.clone_db_user,
            password=settings.clone_db_password,
        )

    # ── Klon İşlemleri ────────────────────────────────────────────────────

    def create_clone(self, job_id: str) -> dict:
        """
        Production'ın anlık klonunu oluşturur.

        1. Varsa eski klonu düşürür.
        2. pg_dump ile production'ı export eder.
        3. Yeni bir DB oluşturup pg_restore ile geri yükler.

        Returns:
            {"success": bool, "elapsed": float, "clone_db": str}
        """
        start = time.time()
        clone_name = settings.clone_db_name
        logger.info(f"[{job_id}] Klon oluşturuluyor: {clone_name}")

        try:
            self._drop_clone_if_exists(clone_name)
            self._create_empty_clone(clone_name)
            self._restore_dump(clone_name, job_id)
            elapsed = time.time() - start
            logger.info(f"[{job_id}] Klon hazır ({elapsed:.1f}s): {clone_name}")
            return {"success": True, "elapsed": elapsed, "clone_db": clone_name}
        except Exception as exc:
            logger.error(f"[{job_id}] Klon hatası: {exc}")
            return {"success": False, "error": str(exc), "elapsed": time.time() - start}

    def _drop_clone_if_exists(self, clone_name: str):
        """Varsa eski klon DB'yi siler."""
        conn = self._clone_conn(dbname="postgres")
        conn.autocommit = True
        try:
            cur = conn.cursor()
            # Aktif bağlantıları kapat
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (clone_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{clone_name}"')
            cur.close()
        finally:
            conn.close()

    def _create_empty_clone(self, clone_name: str):
        """Boş bir klon DB oluşturur."""
        conn = self._clone_conn(dbname="postgres")
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute(f'CREATE DATABASE "{clone_name}"')
            cur.close()
        finally:
            conn.close()

    # PG 17 dump'larında gelen ama PG 16'da desteklenmeyen parametreler
    _UNSUPPORTED_SET_PARAMS = frozenset([
        "transaction_timeout",
    ])

    def _restore_dump(self, clone_name: str, job_id: str):
        """pg_dump (plain) → Python filtresi → psql ile veriyi kopyalar.

        pg_dump araçları PG 17 formatında çıktı üretebilir; bu durumda
        PG 16 sunucusunun tanımadığı SET parametrelerini Python tarafında
        filtreleyerek uyumlu hâle getiriyoruz.
        """
        dump_cmd = [
            "pg_dump",
            "-h", settings.prod_db_host,
            "-p", str(settings.prod_db_port),
            "-U", settings.prod_db_user,
            "-d", settings.prod_db_name,
            "--format=plain",
            "--no-acl",
            "--no-owner",
        ]

        # Dump al
        dump_result = subprocess.run(
            dump_cmd,
            capture_output=True,
            env=self._prod_env,
        )
        if dump_result.returncode != 0:
            raise RuntimeError(f"pg_dump başarısız: {dump_result.stderr.decode()}")

        # Desteklenmeyen SET satırlarını filtrele
        raw_sql = dump_result.stdout.decode("utf-8", errors="replace")
        filtered_lines = [
            line for line in raw_sql.splitlines(keepends=True)
            if not any(
                f"SET {p}" in line or f"set {p}" in line
                for p in self._UNSUPPORTED_SET_PARAMS
            )
        ]
        filtered_sql = "".join(filtered_lines).encode("utf-8")

        psql_cmd = [
            "psql",
            "-h", settings.clone_db_host,
            "-p", str(settings.clone_db_port),
            "-U", settings.clone_db_user,
            "-d", clone_name,
            "--set=ON_ERROR_STOP=1",
        ]

        restore_result = subprocess.run(
            psql_cmd,
            input=filtered_sql,
            capture_output=True,
            env=self._env,
        )
        if restore_result.returncode != 0:
            raise RuntimeError(
                f"pg_restore başarısız: {restore_result.stderr.decode()}"
            )

    # ── SQL Uygulama ─────────────────────────────────────────────────────

    def apply_sql_to_clone(self, sql: str, job_id: str) -> dict:
        """
        Verilen SQL'i klona uygular.

        Returns:
            {"success": bool, "rows_affected": int, "error": str|None}
        """
        logger.info(f"[{job_id}] SQL klona uygulanıyor...")
        try:
            conn = self._clone_conn()
            conn.autocommit = False
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.rowcount if cur.rowcount >= 0 else 0
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"[{job_id}] SQL uygulandı, etkilenen satır: {rows}")
            return {"success": True, "rows_affected": rows}
        except Exception as exc:
            logger.error(f"[{job_id}] SQL uygulama hatası: {exc}")
            return {"success": False, "rows_affected": 0, "error": str(exc)}

    # ── Klon Tablosu Sorgulama ───────────────────────────────────────────

    def get_table_stats(self, conn, table: str) -> dict:
        """Belirtilen tablonun istatistiklerini döner."""
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            row_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            columns = {
                row[0]: {"type": row[1], "nullable": row[2] == "YES"}
                for row in cur.fetchall()
            }
            cur.close()
            return {"row_count": row_count, "columns": columns}
        except Exception as exc:
            logger.warning(f"Tablo istatistiği alınamadı ({table}): {exc}")
            return {"row_count": 0, "columns": {}}

    def get_all_tables(self, conn) -> list[str]:
        """Public şemadaki tüm tabloları listeler."""
        cur = conn.cursor()
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [row[0] for row in cur.fetchall()]
        cur.close()
        return tables


clone_engine = CloneEngine()
