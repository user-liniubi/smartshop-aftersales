"""add catalog, logistics, and repair support

Revision ID: a1c2e3f4b5d6
Revises: 7f9b2d4c6e81
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: str | None = "7f9b2d4c6e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("specs_json", sa.JSON(), nullable=True))
    op.execute("UPDATE products SET specs_json = JSON_OBJECT() WHERE specs_json IS NULL")
    op.alter_column("products", "specs_json", existing_type=sa.JSON(), nullable=False)
    op.add_column(
        "products",
        sa.Column("price", sa.Numeric(10, 2), server_default="0.00", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("stock_quantity", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_products_valid_price"),
        "products",
        "price >= 0",
    )
    op.create_check_constraint(
        op.f("ck_products_valid_stock_quantity"),
        "products",
        "stock_quantity >= 0",
    )

    op.add_column("orders", sa.Column("carrier", sa.String(length=50), nullable=True))
    op.add_column("orders", sa.Column("tracking_no", sa.String(length=64), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "logistics_status",
            sa.String(length=32),
            server_default="not_shipped",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("logistics_updated_at", sa.DateTime(timezone=True), nullable=True),
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


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_after_sales_tickets_valid_request_type"),
        "after_sales_tickets",
        "request_type IN ('return', 'exchange')",
    )
    op.drop_column("orders", "logistics_updated_at")
    op.drop_column("orders", "logistics_status")
    op.drop_column("orders", "tracking_no")
    op.drop_column("orders", "carrier")
    op.drop_constraint(
        op.f("ck_products_valid_stock_quantity"),
        "products",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_products_valid_price"),
        "products",
        type_="check",
    )
    op.drop_column("products", "is_active")
    op.drop_column("products", "stock_quantity")
    op.drop_column("products", "price")
    op.drop_column("products", "specs_json")
