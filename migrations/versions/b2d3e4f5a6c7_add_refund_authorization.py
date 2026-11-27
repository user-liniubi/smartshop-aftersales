"""add refund authorization decisions

Revision ID: b2d3e4f5a6c7
Revises: a1c2e3f4b5d6
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d3e4f5a6c7"
down_revision: str | None = "a1c2e3f4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refund_authorization_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("min_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(12, 2), nullable=False),
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
        sa.CheckConstraint("min_amount >= 0", name=op.f("ck_refund_rules_valid_min_amount")),
        sa.CheckConstraint(
            "max_amount >= min_amount",
            name=op.f("ck_refund_rules_valid_amount_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_authorization_rules")),
    )
    op.create_index(
        op.f("ix_refund_authorization_rules_scenario_code"),
        "refund_authorization_rules",
        ["scenario_code"],
        unique=True,
    )

    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("authorization_min", sa.Numeric(12, 2), nullable=False),
        sa.Column("authorization_max", sa.Numeric(12, 2), nullable=False),
        sa.Column("suggested_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("available_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("policy_citations_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("decision_status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_status IN ('auto_approved', 'manual_review', 'rejected')",
            name=op.f("ck_agent_decisions_valid_decision_status"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["after_sales_tickets.id"],
            name=op.f("fk_agent_decisions_ticket_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_decisions")),
        sa.UniqueConstraint("ticket_id", name=op.f("uq_agent_decisions_ticket_id")),
    )

    op.drop_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        "request_type IN ('return', 'exchange', 'repair', 'compensation')",
    )
    op.drop_constraint(
        op.f("ck_after_sales_ticket_events_valid_actor_type"),
        "after_sales_ticket_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_after_sales_ticket_events_valid_actor_type"),
        "after_sales_ticket_events",
        "actor_type IN ('consumer', 'agent', 'system', 'ai')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_after_sales_ticket_events_valid_actor_type"),
        "after_sales_ticket_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_after_sales_ticket_events_valid_actor_type"),
        "after_sales_ticket_events",
        "actor_type IN ('consumer', 'agent', 'system')",
    )
    op.drop_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        "request_type IN ('return', 'exchange', 'repair')",
    )
    op.drop_table("agent_decisions")
    op.drop_index(
        op.f("ix_refund_authorization_rules_scenario_code"),
        table_name="refund_authorization_rules",
    )
    op.drop_table("refund_authorization_rules")
