"""Initial migration — audit_logs tablosu oluştur

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("sql_command", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_job_id", "audit_logs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_job_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_table("audit_logs")
