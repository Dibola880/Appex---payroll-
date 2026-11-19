"""Add authoritative currency to payroll runs.

Revision ID: p10_payroll_currency_01
Revises: p9_partner_review_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p10_payroll_currency_01"
down_revision = "p9_partner_review_01"
branch_labels = None
depends_on = None


def upgrade():
    # Historical payroll runs remain NULL until separately reconciled.
    # No default or automatic historical backfill is applied here.
    op.add_column(
        "payroll_run",
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=True,
        ),
    )


def downgrade():
    bind = op.get_bind()
    populated = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM payroll_run "
            "WHERE currency IS NOT NULL"
        )
    ).scalar_one()

    if populated:
        raise RuntimeError(
            "Refusing to remove payroll_run.currency: "
            f"{populated} payroll run(s) already have currency values."
        )

    op.drop_column("payroll_run", "currency")
