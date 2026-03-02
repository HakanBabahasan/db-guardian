"""
DB Guardian — Diff Analiz Motoru.

Production snapshot ile klon sonrası durumu karşılaştırır.
Rapor: satır değişimleri, tip uyumsuzlukları, NULL oranları, constraint ihlalleri.
"""
from __future__ import annotations

import logging

import psycopg2
from psycopg2 import sql as pgsql   # güvenli identifier quoting

from src.config import settings
from src.models.schemas import DiffResult, RiskLevel, TableDiff

logger = logging.getLogger("guardian.diff")


class DiffAnalyzer:
    """İki PostgreSQL veritabanı arasındaki farkı analiz eder."""

    # Satır kaybı eşikleri
    _CRITICAL_LOSS_RATIO = 0.50   # %50+ satır kaybı → CRITICAL
    _HIGH_LOSS_RATIO = 0.10       # %10+ satır kaybı → HIGH

    def analyze(self, prod_snapshot: dict, clone_snapshot: dict) -> DiffResult:
        """
        prod_snapshot ve clone_snapshot arasındaki farkı hesaplar.

        Snapshot formatı:
            {
                "tables": {
                    "table_name": {
                        "row_count": int,
                        "columns": {"col": {"type": str, "nullable": bool}, ...}
                    }
                }
            }
        """
        table_diffs: list[TableDiff] = []
        risk_reasons: list[str] = []
        overall_risk = RiskLevel.LOW
        total_row_loss = 0

        prod_tables = prod_snapshot.get("tables", {})
        clone_tables = clone_snapshot.get("tables", {})

        all_tables = set(prod_tables) | set(clone_tables)

        for table_name in sorted(all_tables):
            prod_info = prod_tables.get(table_name, {"row_count": 0, "columns": {}})
            clone_info = clone_tables.get(table_name, {"row_count": 0, "columns": {}})

            diff = self._diff_table(table_name, prod_info, clone_info)
            table_diffs.append(diff)

            # Risk değerlendirmesi
            risk, reasons = self._evaluate_risk(diff, prod_info)
            overall_risk = self._max_risk(overall_risk, risk)
            risk_reasons.extend(reasons)

            if diff.row_delta < 0:
                total_row_loss += abs(diff.row_delta)

        is_refactor = self._detect_refactor(table_diffs)
        if is_refactor and overall_risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            overall_risk = RiskLevel.LOW
            risk_reasons = ["Sadece sıralama/refactor değişikliği tespit edildi."]

        summary = self._build_summary(table_diffs, overall_risk, total_row_loss)

        return DiffResult(
            tables=table_diffs,
            risk_level=overall_risk,
            risk_reasons=risk_reasons,
            is_refactor_only=is_refactor,
            total_row_loss=total_row_loss,
            summary=summary,
        )

    # ── Tablo Diff ───────────────────────────────────────────────────────

    def _diff_table(self, name: str, prod: dict, clone: dict) -> TableDiff:
        prod_cols = prod.get("columns", {})
        clone_cols = clone.get("columns", {})

        dropped = [c for c in prod_cols if c not in clone_cols]
        added = [c for c in clone_cols if c not in prod_cols]

        type_changes: dict[str, tuple[str, str]] = {}
        null_changes: dict[str, int] = {}
        constraint_changes: list[str] = []

        common = set(prod_cols) & set(clone_cols)
        for col in common:
            p = prod_cols[col]
            c = clone_cols[col]
            if p["type"] != c["type"]:
                type_changes[col] = (p["type"], c["type"])
            if p["nullable"] != c["nullable"]:
                constraint_changes.append(
                    f"{col}: nullable {p['nullable']} → {c['nullable']}"
                )
            # NULL oranı karşılaştırması
            p_null = p.get("null_count", 0)
            c_null = c.get("null_count", 0)
            if p_null != c_null:
                null_changes[col] = c_null - p_null

        return TableDiff(
            table_name=name,
            before_row_count=prod["row_count"],
            after_row_count=clone["row_count"],
            row_delta=clone["row_count"] - prod["row_count"],
            null_changes=null_changes,
            type_changes=type_changes,
            dropped_columns=dropped,
            added_columns=added,
            constraint_changes=constraint_changes,
        )

    # ── Risk Değerlendirmesi ─────────────────────────────────────────────

    def _evaluate_risk(self, diff: TableDiff, prod_info: dict) -> tuple[RiskLevel, list[str]]:
        reasons: list[str] = []
        risk = RiskLevel.LOW
        prod_rows = prod_info.get("row_count", 0)

        # Satır kaybı analizi
        if diff.row_delta < 0 and prod_rows > 0:
            loss_ratio = abs(diff.row_delta) / max(prod_rows, 1)
            if loss_ratio >= self._CRITICAL_LOSS_RATIO:
                risk = self._max_risk(risk, RiskLevel.CRITICAL)
                reasons.append(
                    f"{diff.table_name}: %{loss_ratio*100:.0f} satır kaybı (KRİTİK)"
                )
            elif loss_ratio >= self._HIGH_LOSS_RATIO:
                risk = self._max_risk(risk, RiskLevel.HIGH)
                reasons.append(
                    f"{diff.table_name}: %{loss_ratio*100:.0f} satır kaybı (YÜKSEK)"
                )
            else:
                risk = self._max_risk(risk, RiskLevel.MEDIUM)
                reasons.append(f"{diff.table_name}: {abs(diff.row_delta)} satır silindi")

        # Kolon silindi
        if diff.dropped_columns:
            risk = self._max_risk(risk, RiskLevel.CRITICAL)
            reasons.append(
                f"{diff.table_name}: kolon silindi → {diff.dropped_columns}"
            )

        # Tip değişikliği
        for col, (old_t, new_t) in diff.type_changes.items():
            if self._is_type_shrink(old_t, new_t):
                risk = self._max_risk(risk, RiskLevel.HIGH)
                reasons.append(
                    f"{diff.table_name}.{col}: tip küçültme {old_t} → {new_t} (overflow riski)"
                )
            else:
                risk = self._max_risk(risk, RiskLevel.MEDIUM)
                reasons.append(f"{diff.table_name}.{col}: tip değişti {old_t} → {new_t}")

        # Constraint değişikliği
        if diff.constraint_changes:
            risk = self._max_risk(risk, RiskLevel.MEDIUM)
            for change in diff.constraint_changes:
                reasons.append(f"{diff.table_name}: kısıt değişti — {change}")

        return risk, reasons

    # ── Refactor Tespiti ─────────────────────────────────────────────────

    def _detect_refactor(self, diffs: list[TableDiff]) -> bool:
        """
        Tüm tablolarda satır sayısı ve kolon yapısı aynıysa bu bir
        sıralama/refactor değişikliğidir; tehlikeli değil.
        """
        return all(
            diff.row_delta == 0
            and not diff.dropped_columns
            and not diff.type_changes
            and not diff.constraint_changes
            for diff in diffs
        )

    # ── Yardımcılar ──────────────────────────────────────────────────────

    _RISK_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def _max_risk(self, a: RiskLevel, b: RiskLevel) -> RiskLevel:
        return a if self._RISK_ORDER.index(a) >= self._RISK_ORDER.index(b) else b

    def _is_type_shrink(self, old_type: str, new_type: str) -> bool:
        """Tip küçültme mi? (örn: bigint → int, varchar(255) → varchar(10))"""
        shrink_pairs = [
            ("bigint", "integer"), ("bigint", "smallint"),
            ("integer", "smallint"),
            ("double precision", "real"), ("double precision", "float4"),
            ("numeric", "integer"),
            ("text", "varchar"), ("text", "char"),
        ]
        old = old_type.lower().split("(")[0].strip()
        new = new_type.lower().split("(")[0].strip()
        return (old, new) in shrink_pairs

    def _build_summary(
        self, diffs: list[TableDiff], risk: RiskLevel, total_loss: int
    ) -> str:
        changed = [d for d in diffs if d.row_delta != 0 or d.dropped_columns or d.type_changes]
        if not changed:
            return f"Şema veya satır değişikliği tespit edilmedi. Risk: {risk}"
        lines = [f"Risk Seviyesi: {risk} | Toplam satır kaybı: {total_loss}"]
        for d in changed:
            lines.append(
                f"  • {d.table_name}: satır Δ={d.row_delta:+d}"
                + (f", silinen kolon: {d.dropped_columns}" if d.dropped_columns else "")
                + (f", tip değişimi: {list(d.type_changes.keys())}" if d.type_changes else "")
            )
        return "\n".join(lines)


# ── Snapshot alma yardımcısı ─────────────────────────────────────────────────

def take_db_snapshot(dsn: str) -> dict:
    """
    Bir veritabanının tablo istatistiklerini çeker (snapshot formatı).
    """
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    # Tabloları listele
    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    tables = [row[0] for row in cur.fetchall()]

    snapshot: dict = {"tables": {}, "taken_at": __import__("datetime").datetime.utcnow().isoformat()}

    for table in tables:
        try:
            cur.execute(pgsql.SQL("SELECT COUNT(*) FROM {}").format(pgsql.Identifier(table)))
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
            columns = {}
            for col_name, col_type, is_nullable in cur.fetchall():
                # Her kolon için NULL sayısını hesapla
                if row_count > 0:
                    cur.execute(
                        pgsql.SQL("SELECT COUNT(*) FROM {} WHERE {} IS NULL").format(
                            pgsql.Identifier(table),
                            pgsql.Identifier(col_name),
                        )
                    )
                    null_count = cur.fetchone()[0]
                else:
                    null_count = 0
                columns[col_name] = {
                    "type": col_type,
                    "nullable": is_nullable == "YES",
                    "null_count": null_count,
                }
            snapshot["tables"][table] = {"row_count": row_count, "columns": columns}
        except Exception as exc:
            logger.warning(f"Snapshot alınamadı ({table}): {exc}")

    cur.close()
    conn.close()
    return snapshot


diff_analyzer = DiffAnalyzer()
