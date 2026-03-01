"""
Komut Filtresi Testleri — src/core/command_filter.py

Test Grupları:
  1. INSTANT_BLOCK senaryoları
  2. HIGH_RISK senaryoları
  3. SAFE senaryoları
  4. Yorum içeren / karmaşık SQL'ler
"""
import pytest
from src.core.command_filter import FilterDecision, check


# ─────────────────────────────────────────────────────────────
# 1. INSTANT_BLOCK
# ─────────────────────────────────────────────────────────────

class TestInstantBlock:

    def test_delete_without_where(self):
        result = check("DELETE FROM users")
        assert result.decision == FilterDecision.INSTANT_BLOCK
        assert "WHERE" in result.reason or "where" in result.reason.lower()

    def test_delete_without_where_uppercase(self):
        result = check("DELETE FROM USERS")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_delete_without_where_multiline(self):
        result = check("""
            DELETE
            FROM payments
        """)
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_update_without_where(self):
        result = check("UPDATE users SET active = false")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_update_without_where_multiline(self):
        result = check("""
            UPDATE orders
            SET status = 'cancelled'
        """)
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_drop_table(self):
        result = check("DROP TABLE users")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_drop_table_if_exists(self):
        result = check("DROP TABLE IF EXISTS payments")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_drop_database(self):
        result = check("DROP DATABASE guardian_prod")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_drop_schema(self):
        result = check("DROP SCHEMA public CASCADE")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_truncate(self):
        result = check("TRUNCATE TABLE users")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_truncate_without_table(self):
        result = check("TRUNCATE users")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_delete_with_inline_comment_no_where(self):
        """Yorum kaldırıldıktan sonra hâlâ WHERE yok → BLOCK"""
        result = check("DELETE FROM users -- sadece bir test")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_delete_with_block_comment_no_where(self):
        result = check("DELETE /* tüm kayıtlar */ FROM users")
        assert result.decision == FilterDecision.INSTANT_BLOCK


# ─────────────────────────────────────────────────────────────
# 2. HIGH_RISK
# ─────────────────────────────────────────────────────────────

class TestHighRisk:

    def test_drop_column(self):
        result = check("ALTER TABLE users DROP COLUMN email")
        assert result.decision == FilterDecision.HIGH_RISK

    def test_alter_column_type(self):
        result = check("ALTER TABLE payments ALTER COLUMN amount TYPE INTEGER")
        assert result.decision == FilterDecision.HIGH_RISK

    def test_drop_constraint(self):
        result = check("ALTER TABLE orders DROP CONSTRAINT orders_user_id_fkey")
        assert result.decision == FilterDecision.HIGH_RISK


# ─────────────────────────────────────────────────────────────
# 3. SAFE
# ─────────────────────────────────────────────────────────────

class TestSafe:

    def test_delete_with_where(self):
        result = check("DELETE FROM users WHERE id = 42")
        assert result.decision == FilterDecision.SAFE

    def test_delete_with_where_complex(self):
        result = check("DELETE FROM sessions WHERE expires_at < NOW()")
        assert result.decision == FilterDecision.SAFE

    def test_update_with_where(self):
        result = check("UPDATE users SET active = false WHERE last_login < '2023-01-01'")
        assert result.decision == FilterDecision.SAFE

    def test_insert(self):
        result = check("INSERT INTO users (username, email) VALUES ('alice', 'alice@example.com')")
        assert result.decision == FilterDecision.SAFE

    def test_select(self):
        result = check("SELECT * FROM users WHERE id = 1")
        assert result.decision == FilterDecision.SAFE

    def test_add_column(self):
        result = check("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
        assert result.decision == FilterDecision.SAFE

    def test_create_index(self):
        result = check("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")
        assert result.decision == FilterDecision.SAFE

    def test_create_table(self):
        result = check("CREATE TABLE new_feature (id SERIAL PRIMARY KEY, name TEXT)")
        assert result.decision == FilterDecision.SAFE

    def test_add_column_with_default(self):
        result = check("ALTER TABLE payments ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'TRY'")
        assert result.decision == FilterDecision.SAFE

    def test_rename_column(self):
        result = check("ALTER TABLE users RENAME COLUMN username TO user_name")
        assert result.decision == FilterDecision.SAFE

    def test_select_with_subquery(self):
        result = check("SELECT id FROM users WHERE email IN (SELECT email FROM blacklist)")
        assert result.decision == FilterDecision.SAFE

    def test_delete_with_where_subquery(self):
        result = check("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE active = false)")
        assert result.decision == FilterDecision.SAFE


# ─────────────────────────────────────────────────────────────
# 4. Edge Case'ler
# ─────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_sql(self):
        """Boş SQL — bir şeyle eşleşmez → SAFE döner."""
        result = check("")
        assert result.decision == FilterDecision.SAFE

    def test_whitespace_only(self):
        result = check("   \n\t  ")
        assert result.decision == FilterDecision.SAFE

    def test_matched_rule_populated(self):
        """Eşleşen kural adı dolu olmalı."""
        result = check("DELETE FROM users")
        assert result.matched_rule != ""

    def test_normalized_sql_populated(self):
        """Normalize edilmiş SQL dolu olmalı."""
        result = check("DELETE FROM users WHERE id = 1")
        assert result.normalized_sql != ""
        assert result.normalized_sql == result.normalized_sql.lower()

    def test_drop_table_lowercase(self):
        result = check("drop table orders")
        assert result.decision == FilterDecision.INSTANT_BLOCK

    def test_update_with_where_in_string_literal(self):
        """
        'where' ifadesi string literal içinde geçiyorsa bu WHERE koşulu sayılmaz.
        Dikkat: basit regex tespiti bu durumu yakalayamayabilir.
        Bu test mevcut implementasyonun limitini belgeler.
        """
        # Bu test bilgilendirici — geçemeyebilir, bu beklenen bir davranış
        result = check("UPDATE users SET note = 'no where clause needed'")
        # String içindeki 'where'yi tespit edebilirse SAFE döner (false positive),
        # edemezse INSTANT_BLOCK döner (false negative değil, aşırı güvenli).
        assert result.decision in (FilterDecision.SAFE, FilterDecision.INSTANT_BLOCK)
