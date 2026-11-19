"""Create append-only platform audit log foundation.

Revision ID: p7_audit_01
Revises: p7_billing_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p7_audit_01"
down_revision = "p7_billing_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_role",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "target_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "ix_platform_audit_company_created",
        "platform_audit_log",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_actor_created",
        "platform_audit_log",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_action_created",
        "platform_audit_log",
        ["action", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_log_created_at",
        "platform_audit_log",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_platform_audit_log_created_at",
        table_name="platform_audit_log",
    )
    op.drop_index(
        "ix_platform_audit_action_created",
        table_name="platform_audit_log",
    )
    op.drop_index(
        "ix_platform_audit_actor_created",
        table_name="platform_audit_log",
    )
    op.drop_index(
        "ix_platform_audit_company_created",
        table_name="platform_audit_log",
    )
    op.drop_table("platform_audit_log")
