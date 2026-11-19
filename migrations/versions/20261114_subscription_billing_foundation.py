"""Create subscription invoice, invoice item and payment foundations.

Revision ID: p7_billing_01
Revises: p7_subscription_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p7_billing_01"
down_revision = "p7_subscription_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("company_subscription.id"),
            nullable=False,
        ),
        sa.Column("invoice_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance_due", sa.Numeric(12, 2), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "invoice_number",
            name="uq_subscription_invoice_number",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND tax_amount >= 0 AND total >= 0",
            name="ck_subscription_invoice_nonnegative_totals",
        ),
        sa.CheckConstraint(
            "amount_paid >= 0 AND balance_due >= 0",
            name="ck_subscription_invoice_nonnegative_balance",
        ),
    )

    op.create_index(
        "ix_subscription_invoice_company_status",
        "subscription_invoice",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_subscription_invoice_subscription_id",
        "subscription_invoice",
        ["subscription_id"],
    )

    op.create_table(
        "subscription_invoice_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("subscription_invoice.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("subscription_plan.id"),
            nullable=True,
        ),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_subscription_invoice_item_positive_quantity",
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0",
            name="ck_subscription_invoice_item_nonnegative_amounts",
        ),
    )

    op.create_index(
        "ix_subscription_invoice_item_invoice_id",
        "subscription_invoice_item",
        ["invoice_id"],
    )

    op.create_table(
        "subscription_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("subscription_invoice.id"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payment_provider", sa.String(length=50), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_subscription_payment_idempotency_key",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_subscription_payment_positive_amount",
        ),
    )

    op.create_index(
        "ix_subscription_payment_company_status",
        "subscription_payment",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_subscription_payment_invoice_status",
        "subscription_payment",
        ["invoice_id", "status"],
    )
    op.create_index(
        "ix_subscription_payment_provider_reference",
        "subscription_payment",
        ["payment_provider", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text(
            "payment_provider IS NOT NULL AND provider_payment_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "payment_provider IS NOT NULL AND provider_payment_id IS NOT NULL"
        ),
    )


def downgrade():
    # Billing history is financial evidence. Export and review it before
    # any downgrade that would permanently remove invoices or payments.
    op.drop_index(
        "ix_subscription_payment_provider_reference",
        table_name="subscription_payment",
    )
    op.drop_index(
        "ix_subscription_payment_invoice_status",
        table_name="subscription_payment",
    )
    op.drop_index(
        "ix_subscription_payment_company_status",
        table_name="subscription_payment",
    )
    op.drop_table("subscription_payment")

    op.drop_index(
        "ix_subscription_invoice_item_invoice_id",
        table_name="subscription_invoice_item",
    )
    op.drop_table("subscription_invoice_item")

    op.drop_index(
        "ix_subscription_invoice_subscription_id",
        table_name="subscription_invoice",
    )
    op.drop_index(
        "ix_subscription_invoice_company_status",
        table_name="subscription_invoice",
    )
    op.drop_table("subscription_invoice")
