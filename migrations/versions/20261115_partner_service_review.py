"""Add independent partner service request review governance.

Revision ID: p9_partner_review_01
Revises: p9_partner_consent_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p9_partner_review_01"
down_revision = "p9_partner_consent_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "partner_service_request_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="RESTRICT"),
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
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason_code", sa.String(80), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'prepared')",
            name="ck_partner_request_review_status",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_partner_request_review_hash_length",
        ),
        sa.CheckConstraint(
            "reviewed_by_user_id IS NULL OR "
            "reviewed_by_user_id != requested_by_user_id",
            name="ck_partner_request_review_independent_reviewer",
        ),
        sa.UniqueConstraint(
            "integration_id",
            "request_id",
            name="uq_partner_request_review_integration_request",
        ),
    )

    op.create_index(
        "ix_partner_request_review_company_status",
        "partner_service_request_review",
        ["company_id", "status", "submitted_at"],
    )
    op.create_index(
        "ix_partner_request_review_integration_status",
        "partner_service_request_review",
        ["integration_id", "status", "expires_at"],
    )

    op.create_table(
        "partner_service_request_review_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey(
                "partner_service_request_review.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="RESTRICT"),
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
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('submitted', 'approved', 'rejected', 'expired', 'prepared')",
            name="ck_partner_request_review_event_type",
        ),
        sa.CheckConstraint(
            "to_status IN ('pending', 'approved', 'rejected', 'expired', 'prepared')",
            name="ck_partner_request_review_event_to_status",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR "
            "from_status IN ('pending', 'approved', 'rejected', 'expired', 'prepared')",
            name="ck_partner_request_review_event_from_status",
        ),
    )

    op.create_index(
        "ix_partner_request_review_event_company_created",
        "partner_service_request_review_event",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_partner_request_review_event_review_created",
        "partner_service_request_review_event",
        ["review_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_partner_request_review_event_review_created",
        table_name="partner_service_request_review_event",
    )
    op.drop_index(
        "ix_partner_request_review_event_company_created",
        table_name="partner_service_request_review_event",
    )
    op.drop_table("partner_service_request_review_event")

    op.drop_index(
        "ix_partner_request_review_integration_status",
        table_name="partner_service_request_review",
    )
    op.drop_index(
        "ix_partner_request_review_company_status",
        table_name="partner_service_request_review",
    )
    op.drop_table("partner_service_request_review")
