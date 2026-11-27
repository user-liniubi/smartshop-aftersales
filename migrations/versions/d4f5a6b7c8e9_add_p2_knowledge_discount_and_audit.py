"""add p2 knowledge categories, discount authorization and audit

Revision ID: d4f5a6b7c8e9
Revises: c3e4f5a6b7d8
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f5a6b7c8e9"
down_revision: str | None = "c3e4f5a6b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "category",
            sa.String(length=32),
            server_default="business_policy",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_documents_category"),
        "documents",
        ["category"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_documents_valid_category"),
        "documents",
        "category IN ('product', 'business_policy', 'support_sop')",
    )

    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "category",
            sa.String(length=32),
            server_default="business_policy",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_ingestion_jobs_valid_category"),
        "ingestion_jobs",
        "category IN ('product', 'business_policy', 'support_sop')",
    )

    op.execute("UPDATE documents SET category = 'product' WHERE product_id IS NOT NULL")
    op.execute("UPDATE ingestion_jobs SET category = 'product' WHERE product_id IS NOT NULL")

    op.create_table(
        "discount_authorization_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("max_discount_rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("max_discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_discount_rate > 0",
            name=op.f("ck_discount_authorization_rules_valid_discount_rate"),
        ),
        sa.CheckConstraint(
            "max_discount_rate <= 1",
            name=op.f("ck_discount_authorization_rules_valid_max_discount_rate"),
        ),
        sa.CheckConstraint(
            "max_discount_amount >= 0",
            name=op.f("ck_discount_authorization_rules_valid_discount_amount"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_discount_authorization_rules_product_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discount_authorization_rules")),
    )
    op.create_index(
        op.f("ix_discount_authorization_rules_rule_code"),
        "discount_authorization_rules",
        ["rule_code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_discount_authorization_rules_product_id"),
        "discount_authorization_rules",
        ["product_id"],
        unique=False,
    )

    op.create_table(
        "discount_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_no", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("final_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("policy_citations_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "unit_price > 0",
            name=op.f("ck_discount_quotes_valid_unit_price"),
        ),
        sa.CheckConstraint(
            "discount_rate > 0",
            name=op.f("ck_discount_quotes_valid_discount_rate"),
        ),
        sa.CheckConstraint(
            "discount_rate <= 1",
            name=op.f("ck_discount_quotes_valid_max_discount_rate"),
        ),
        sa.CheckConstraint(
            "discount_amount > 0",
            name=op.f("ck_discount_quotes_valid_discount_amount"),
        ),
        sa.CheckConstraint(
            "final_price >= 0",
            name=op.f("ck_discount_quotes_valid_final_price"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_discount_quotes_product_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["discount_authorization_rules.id"],
            name=op.f("fk_discount_quotes_rule_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_discount_quotes_session_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_discount_quotes_user_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discount_quotes")),
    )
    op.create_index(
        op.f("ix_discount_quotes_quote_no"),
        "discount_quotes",
        ["quote_no"],
        unique=True,
    )
    op.create_index(
        op.f("ix_discount_quotes_session_id"),
        "discount_quotes",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discount_quotes_user_id"),
        "discount_quotes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discount_quotes_product_id"),
        "discount_quotes",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discount_quotes_rule_id"),
        "discount_quotes",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_discount_quotes_session_created_at",
        "discount_quotes",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "config_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_config_audit_logs_actor_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_audit_logs")),
    )
    op.create_index(
        op.f("ix_config_audit_logs_actor_id"),
        "config_audit_logs",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_config_audit_logs_entity_type"),
        "config_audit_logs",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_config_audit_logs_entity_id"),
        "config_audit_logs",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_config_audit_logs_entity_created_at",
        "config_audit_logs",
        ["entity_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_config_audit_logs_entity_created_at",
        table_name="config_audit_logs",
    )
    op.drop_index(op.f("ix_config_audit_logs_entity_id"), table_name="config_audit_logs")
    op.drop_index(op.f("ix_config_audit_logs_entity_type"), table_name="config_audit_logs")
    op.drop_index(op.f("ix_config_audit_logs_actor_id"), table_name="config_audit_logs")
    op.drop_table("config_audit_logs")

    op.drop_index("ix_discount_quotes_session_created_at", table_name="discount_quotes")
    op.drop_index(op.f("ix_discount_quotes_rule_id"), table_name="discount_quotes")
    op.drop_index(op.f("ix_discount_quotes_product_id"), table_name="discount_quotes")
    op.drop_index(op.f("ix_discount_quotes_user_id"), table_name="discount_quotes")
    op.drop_index(op.f("ix_discount_quotes_session_id"), table_name="discount_quotes")
    op.drop_index(op.f("ix_discount_quotes_quote_no"), table_name="discount_quotes")
    op.drop_table("discount_quotes")

    op.drop_index(
        op.f("ix_discount_authorization_rules_product_id"),
        table_name="discount_authorization_rules",
    )
    op.drop_index(
        op.f("ix_discount_authorization_rules_rule_code"),
        table_name="discount_authorization_rules",
    )
    op.drop_table("discount_authorization_rules")

    op.drop_constraint(
        op.f("ck_ingestion_jobs_valid_category"),
        "ingestion_jobs",
        type_="check",
    )
    op.drop_column("ingestion_jobs", "category")
    op.drop_constraint(
        op.f("ck_documents_valid_category"),
        "documents",
        type_="check",
    )
    op.drop_index(op.f("ix_documents_category"), table_name="documents")
    op.drop_column("documents", "category")
