"""Create subscription plan and company subscription foundation.

Revision ID: p7_subscription_01
Revises: p6_loan_app_01
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "p7_subscription_01"
down_revision = "p6_loan_app_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("monthly_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("annual_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_intervals", sa.JSON(), nullable=False),
        sa.Column("employee_limit", sa.Integer(), nullable=True),
        sa.Column("feature_config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint("code", name="uq_subscription_plan_code"),
    )

    op.create_table(
        "company_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("subscription_plan.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("billing_interval", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("payment_provider", sa.String(length=50), nullable=True),
        sa.Column("provider_customer_id", sa.String(length=200), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=200), nullable=True),
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
    )

    op.create_index(
        "ix_company_subscription_one_current",
        "company_subscription",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
        sqlite_where=sa.text("is_current = true"),
    )

    op.create_index(
        "ix_company_subscription_company_status",
        "company_subscription",
        ["company_id", "status"],
    )

    op.create_index(
        "ix_company_subscription_plan_id",
        "company_subscription",
        ["plan_id"],
    )

    # Seed only the known existing Free Trial offering.
    # No historical company records or unknown plan prices are rewritten.
    plan_table = sa.table(
        "subscription_plan",
        sa.column("code", sa.String(length=64)),
        sa.column("name", sa.String(length=120)),
        sa.column("description", sa.Text()),
        sa.column("monthly_price", sa.Numeric(12, 2)),
        sa.column("annual_price", sa.Numeric(12, 2)),
        sa.column("currency", sa.String(length=3)),
        sa.column("billing_intervals", sa.JSON()),
        sa.column("employee_limit", sa.Integer()),
        sa.column("feature_config", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    now = datetime.utcnow()

    op.bulk_insert(
        plan_table,
        [
            {
                "code": "free_trial",
                "name": "Free Trial",
                "description": "Existing Appex free-trial offering.",
                "monthly_price": 0,
                "annual_price": None,
                "currency": "ZAR",
                "billing_intervals": ["monthly", "annually"],
                "employee_limit": None,
                "feature_config": {},
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade():
    # This removes subscription records and plan configuration.
    # Review and export subscription history before any downgrade.
    op.drop_index(
        "ix_company_subscription_plan_id",
        table_name="company_subscription",
    )
    op.drop_index(
        "ix_company_subscription_company_status",
        table_name="company_subscription",
    )
    op.drop_index(
        "ix_company_subscription_one_current",
        table_name="company_subscription",
    )
    op.drop_table("company_subscription")
    op.drop_table("subscription_plan")
