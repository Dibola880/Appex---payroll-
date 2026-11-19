"""Add missing loan repayment ledger fields.

Revision ID: p6_loan_repay_01
Revises: p6_prod_base_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p6_loan_repay_01"
down_revision = "p6_prod_base_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "loan_repayment",
        sa.Column("balance_before", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_repayment",
        sa.Column("balance_after", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "loan_repayment",
        sa.Column("payment_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "loan_repayment",
        sa.Column("source", sa.String(length=50), nullable=True),
    )


def downgrade():
    op.drop_column("loan_repayment", "source")
    op.drop_column("loan_repayment", "payment_number")
    op.drop_column("loan_repayment", "balance_after")
    op.drop_column("loan_repayment", "balance_before")
