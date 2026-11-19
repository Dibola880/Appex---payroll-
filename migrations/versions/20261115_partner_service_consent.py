"""Add company-scoped partner service consent governance.

Revision ID: p9_partner_consent_01
Revises: p9_partner_audit_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p9_partner_consent_01"
down_revision = "p9_partner_audit_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "partner_service_consent",
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
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("purpose_code", sa.String(80), nullable=False),
        sa.Column("data_categories", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "consent_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "granted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "revoked_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revocation_reason_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_service_consent_status",
        ),
        sa.CheckConstraint(
            "consent_version >= 1",
            name="ck_partner_service_consent_version",
        ),
    )

    op.create_index(
        "ix_partner_consent_scope_status_expiry",
        "partner_service_consent",
        ["company_id", "integration_id", "operation", "status", "expires_at"],
    )
    op.create_index(
        "ix_partner_consent_provider_created",
        "partner_service_consent",
        ["provider_id", "created_at"],
    )



    op.create_table(
        "partner_service_consent_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "consent_id",
            sa.Integer(),
            sa.ForeignKey("partner_service_consent.id", ondelete="RESTRICT"),
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
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'activated', 'revoked', 'expired')",
            name="ck_partner_consent_event_type",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_consent_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_partner_consent_event_to_status",
        ),
    )

    op.create_index(
        "ix_partner_consent_event_company_created",
        "partner_service_consent_event",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_partner_consent_event_consent_created",
        "partner_service_consent_event",
        ["consent_id", "created_at"],
    )

def downgrade():
    op.drop_index(
        "ix_partner_consent_event_consent_created",
        table_name="partner_service_consent_event",
    )
    op.drop_index(
        "ix_partner_consent_event_company_created",
        table_name="partner_service_consent_event",
    )
    op.drop_table("partner_service_consent_event")

    op.drop_index(
        "ix_partner_consent_provider_created",
        table_name="partner_service_consent",
    )
    op.drop_index(
        "ix_partner_consent_scope_status_expiry",
        table_name="partner_service_consent",
    )
    op.drop_table("partner_service_consent")
