"""Add provider payment reconciliation history.

Revision ID: p8_payment_recon_01
Revises: p8_integration_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p8_payment_recon_01"
down_revision = "p8_integration_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_reconciliation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("integration_event.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("company_integration.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("subscription_invoice.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("subscription_payment.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("provider_payment_id", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("reconciled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "event_id",
            name="uq_payment_reconciliation_event",
        ),
        sa.CheckConstraint(
            "outcome IN ('reconciled', 'unmatched', 'mismatch', 'duplicate', 'exception')",
            name="ck_payment_reconciliation_outcome",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0",
            name="ck_payment_reconciliation_positive_amount",
        ),
    )

    op.create_index(
        "ix_payment_reconciliation_company_attempted",
        "payment_reconciliation",
        ["company_id", "attempted_at"],
    )
    op.create_index(
        "ix_payment_reconciliation_provider_reference",
        "payment_reconciliation",
        ["provider_id", "provider_payment_id"],
    )
    op.create_index(
        "uq_payment_reconciliation_success_payment",
        "payment_reconciliation",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text(
            "outcome = 'reconciled' AND payment_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "outcome = 'reconciled' AND payment_id IS NOT NULL"
        ),
    )


def downgrade():
    op.drop_index(
        "uq_payment_reconciliation_success_payment",
        table_name="payment_reconciliation",
    )
    op.drop_index(
        "ix_payment_reconciliation_provider_reference",
        table_name="payment_reconciliation",
    )
    op.drop_index(
        "ix_payment_reconciliation_company_attempted",
        table_name="payment_reconciliation",
    )
    op.drop_table("payment_reconciliation")
