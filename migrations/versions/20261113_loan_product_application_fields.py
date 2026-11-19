"""Add missing loan product and application fields.

Revision ID: p6_loan_app_01
Revises: p6_loan_repay_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p6_loan_app_01"
down_revision = "p6_loan_repay_01"
branch_labels = None
depends_on = None


def upgrade():
    # Existing loan products receive safe configuration defaults.
    op.add_column(
        "loan_product",
        sa.Column(
            "service_fee",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "loan_product",
        sa.Column(
            "max_deduction_percent",
            sa.Float(precision=53),
            server_default=sa.text("30"),
            nullable=False,
        ),
    )
    op.add_column(
        "loan_product",
        sa.Column(
            "minimum_employment_months",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    # Loan application history: do not invent financial breakdown values.
    op.add_column(
        "loan_application",
        sa.Column("repayment_frequency", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column("principal_amount", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column("interest_amount", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column("service_fee_amount", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column("scheduled_installment", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_application",
        sa.Column(
            "number_of_payments",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "loan_application",
        sa.Column("last_payment_date", sa.Date(), nullable=True),
    )

    # Keep the defaults for existing rows, but avoid permanent DB defaults
    # that are not declared in the ORM model.
    op.alter_column("loan_product", "service_fee", server_default=None)
    op.alter_column("loan_product", "max_deduction_percent", server_default=None)
    op.alter_column("loan_product", "minimum_employment_months", server_default=None)
    op.alter_column("loan_application", "number_of_payments", server_default=None)


def downgrade():
    # This removes newly introduced fields; do not run against production
    # without a separate data-retention and rollback review.
    op.drop_column("loan_application", "last_payment_date")
    op.drop_column("loan_application", "number_of_payments")
    op.drop_column("loan_application", "scheduled_installment")
    op.drop_column("loan_application", "service_fee_amount")
    op.drop_column("loan_application", "interest_amount")
    op.drop_column("loan_application", "principal_amount")
    op.drop_column("loan_application", "approved_at")
    op.drop_column("loan_application", "repayment_frequency")

    op.drop_column("loan_product", "minimum_employment_months")
    op.drop_column("loan_product", "max_deduction_percent")
    op.drop_column("loan_product", "service_fee")
