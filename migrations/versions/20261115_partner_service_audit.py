"""Add persistent partner service audit history.

Revision ID: p9_partner_audit_01
Revises: p8_payroll_disb_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p9_partner_audit_01"
down_revision = "p8_payroll_disb_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "partner_service_audit_log",
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
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("partner_reference", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "outcome IN ('prepared', 'rejected')",
            name="ck_partner_service_audit_outcome",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_partner_service_audit_payload_hash_length",
        ),
        sa.UniqueConstraint(
            "integration_id",
            "request_id",
            name="uq_partner_service_audit_integration_request",
        ),
    )

    op.create_index(
        "ix_partner_service_audit_company_created",
        "partner_service_audit_log",
        ["company_id", "created_at"],
    )

    op.create_index(
        "ix_partner_service_audit_provider_operation_created",
        "partner_service_audit_log",
        ["provider_id", "operation", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_partner_service_audit_provider_operation_created",
        table_name="partner_service_audit_log",
    )
    op.drop_index(
        "ix_partner_service_audit_company_created",
        table_name="partner_service_audit_log",
    )
    op.drop_table("partner_service_audit_log")
