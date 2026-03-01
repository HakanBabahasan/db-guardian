"""
DB Guardian — Tehlikeli SQL komut filtresi.

Kural hiyerarşisi:
  INSTANT_BLOCK  → Production'a hiç ulaşmamalı (WHERE'siz DELETE/UPDATE, DROP TABLE/DATABASE)
  HIGH_RISK      → Manuel inceleme gerektirir
  SAFE           → Otomatik onay yoluna alınır
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class FilterDecision(str, Enum):
    INSTANT_BLOCK = "INSTANT_BLOCK"
    HIGH_RISK = "HIGH_RISK"
    SAFE = "SAFE"


@dataclass
class FilterResult:
    decision: FilterDecision
    reason: str
    matched_rule: str = ""
    normalized_sql: str = ""


# ── Normalleştirme ────────────────────────────────────────────────────────────

def _normalize(sql: str) -> str:
    """SQL'i küçük harfe çevirir, fazla boşlukları temizler, satır sonlarını düzler."""
    sql = sql.strip()
    sql = re.sub(r"--[^\n]*", "", sql)           # satır içi yorumları kaldır
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)  # blok yorumları kaldır
    sql = re.sub(r"\s+", " ", sql)               # çoklu boşluk → tek boşluk
    return sql.lower().strip()


# ── Kural tanımları ──────────────────────────────────────────────────────────

@dataclass
class Rule:
    name: str
    pattern: re.Pattern
    decision: FilterDecision
    reason: str


# WHERE koşulsuz DELETE/UPDATE tespiti
# Mantık: komut 'delete from <tablo>' veya 'update <tablo> set ...' ile başlıyor
# ve sonrasında 'where' anahtar kelimesi GELMİYOR.
_RULES: list[Rule] = [
    # ── INSTANT_BLOCK ─────────────────────────────────────────────────────
    Rule(
        name="DROP_TABLE",
        pattern=re.compile(r"\bdrop\s+table\b"),
        decision=FilterDecision.INSTANT_BLOCK,
        reason="DROP TABLE komutu production'da kabul edilmez. Önce backup alın, ardından break-glass kullanın.",
    ),
    Rule(
        name="DROP_DATABASE",
        pattern=re.compile(r"\bdrop\s+database\b"),
        decision=FilterDecision.INSTANT_BLOCK,
        reason="DROP DATABASE komutu kesinlikle engellendi.",
    ),
    Rule(
        name="DROP_SCHEMA",
        pattern=re.compile(r"\bdrop\s+schema\b"),
        decision=FilterDecision.INSTANT_BLOCK,
        reason="DROP SCHEMA komutu anında engellendi.",
    ),
    Rule(
        name="TRUNCATE_TABLE",
        pattern=re.compile(r"\btruncate\b"),
        decision=FilterDecision.INSTANT_BLOCK,
        reason="TRUNCATE tüm verileri siler, WHERE koşulu desteklemez. Kesinlikle engellendi.",
    ),
    # ── HIGH_RISK ─────────────────────────────────────────────────────────
    Rule(
        name="DROP_COLUMN",
        pattern=re.compile(r"\balter\s+table\b.*\bdrop\s+column\b"),
        decision=FilterDecision.HIGH_RISK,
        reason="Kolon silme işlemi veri kaybına neden olabilir. Manuel inceleme gerekli.",
    ),
    Rule(
        name="ALTER_COLUMN_TYPE",
        pattern=re.compile(r"\balter\s+table\b.*\balter\s+column\b.*\btype\b"),
        decision=FilterDecision.HIGH_RISK,
        reason="Kolon tipi değişikliği overflow veya veri bozulması riski taşır.",
    ),
    Rule(
        name="DROP_CONSTRAINT",
        pattern=re.compile(r"\balter\s+table\b.*\bdrop\s+constraint\b"),
        decision=FilterDecision.HIGH_RISK,
        reason="Kısıt kaldırma veri bütünlüğünü tehlikeye atabilir.",
    ),
]


# ── WHERE koşulsuz DML tespiti ────────────────────────────────────────────────

def _is_delete_without_where(sql_norm: str) -> bool:
    """DELETE FROM <tablo> ifadesi var ama WHERE yok mu?"""
    if not re.search(r"\bdelete\s+from\b", sql_norm):
        return False
    return not re.search(r"\bwhere\b", sql_norm)


def _is_update_without_where(sql_norm: str) -> bool:
    """UPDATE <tablo> SET ... ifadesi var ama WHERE yok mu?"""
    if not re.search(r"\bupdate\b", sql_norm):
        return False
    if not re.search(r"\bset\b", sql_norm):
        return False
    return not re.search(r"\bwhere\b", sql_norm)


# ── Ana kontrol fonksiyonu ────────────────────────────────────────────────────

def check(sql: str) -> FilterResult:
    """
    SQL komutunu filtreler ve bir FilterResult döner.

    Kullanım:
        result = check("DELETE FROM users")
        if result.decision == FilterDecision.INSTANT_BLOCK:
            raise ...
    """
    normalized = _normalize(sql)

    # WHERE koşulsuz DELETE — anında blok
    if _is_delete_without_where(normalized):
        return FilterResult(
            decision=FilterDecision.INSTANT_BLOCK,
            reason="WHERE koşulsuz DELETE tüm tablo verilerini siler. Kesinlikle engellendi.",
            matched_rule="DELETE_WITHOUT_WHERE",
            normalized_sql=normalized,
        )

    # WHERE koşulsuz UPDATE — anında blok
    if _is_update_without_where(normalized):
        return FilterResult(
            decision=FilterDecision.INSTANT_BLOCK,
            reason="WHERE koşulsuz UPDATE tüm satırları günceller. Kesinlikle engellendi.",
            matched_rule="UPDATE_WITHOUT_WHERE",
            normalized_sql=normalized,
        )

    # Statik kural kontrolü
    for rule in _RULES:
        if rule.pattern.search(normalized):
            return FilterResult(
                decision=rule.decision,
                reason=rule.reason,
                matched_rule=rule.name,
                normalized_sql=normalized,
            )

    return FilterResult(
        decision=FilterDecision.SAFE,
        reason="Komut tehlikeli kural eşleşmesi bulunamadı.",
        normalized_sql=normalized,
    )
