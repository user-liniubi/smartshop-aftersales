"""add refund execution records

Revision ID: c3e4f5a6b7d8
Revises: b2d3e4f5a6c7
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e4f5a6b7d8"
down_revision: str | None = "b2d3e4f5a6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_agent_decisions_valid_decision_status"),
        "agent_decisions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_agent_decisions_valid_decision_status"),
        "agent_decisions",
        "decision_status IN ('auto_approved', 'manually_approved', 'manual_review', 'rejected')",
    )

    op.create_table(
        "refund_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_refund_executions_valid_amount")),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name=op.f("ck_refund_executions_valid_attempt_count"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed')",
            name=op.f("ck_refund_executions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["after_sales_tickets.id"],
            name=op.f("fk_refund_executions_ticket_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_executions")),
        sa.UniqueConstraint("ticket_id", name=op.f("uq_refund_executions_ticket_id")),
    )
    op.create_index(
        op.f("ix_refund_executions_idempotency_key"),
        "refund_executions",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_refund_executions_idempotency_key"),
        table_name="refund_executions",
    )
    op.drop_table("refund_executions")
    op.drop_constraint(
        op.f("ck_agent_decisions_valid_decision_status"),
        "agent_decisions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_agent_decisions_valid_decision_status"),
        "agent_decisions",
        "decision_status IN ('auto_approved', 'manual_review', 'rejected')",
    )
