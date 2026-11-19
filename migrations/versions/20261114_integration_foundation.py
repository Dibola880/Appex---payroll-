"""Create provider integration foundation.

Revision ID: p8_integration_01
Revises: p7_audit_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p8_integration_01"
down_revision = "p7_audit_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint("code", name="uq_integration_provider_code"),
    )

    op.create_index(
        "ix_integration_provider_category_enabled",
        "integration_provider",
        ["category", "is_enabled"],
    )

    op.create_table(
        "company_integration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ownership_scope", sa.String(length=20), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("credential_key_version", sa.String(length=40), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
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
        sa.CheckConstraint(
            "ownership_scope IN ('platform', 'company')",
            name="ck_company_integration_ownership_scope",
        ),
        sa.CheckConstraint(
            "(ownership_scope = 'platform' AND company_id IS NULL) OR "
            "(ownership_scope = 'company' AND company_id IS NOT NULL)",
            name="ck_company_integration_scope_company",
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox', 'production')",
            name="ck_company_integration_environment",
        ),
        sa.CheckConstraint(
            "status IN ('not_connected', 'pending', 'connected', 'error', 'disabled')",
            name="ck_company_integration_status",
        ),
    )

    op.create_index(
        "ix_company_integration_company_status",
        "company_integration",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_company_integration_provider_status",
        "company_integration",
        ["provider_id", "status"],
    )
    op.create_index(
        "uq_company_integration_company_provider_env",
        "company_integration",
        ["company_id", "provider_id", "environment"],
        unique=True,
        postgresql_where=sa.text("company_id IS NOT NULL"),
        sqlite_where=sa.text("company_id IS NOT NULL"),
    )
    op.create_index(
        "uq_company_integration_platform_provider_env",
        "company_integration",
        ["provider_id", "environment"],
        unique=True,
        postgresql_where=sa.text("company_id IS NULL"),
        sqlite_where=sa.text("company_id IS NULL"),
    )

    op.create_table(
        "integration_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("integration_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("company_integration.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_event_id", sa.String(length=200), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("provider_timestamp", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("processing_token", sa.String(length=64), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("processing_lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "processing_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "processing_attempts >= 0",
            name="ck_integration_event_processing_attempts",
        ),

        sa.CheckConstraint(
            "status IN ('received', 'verified', 'processing', 'processed', 'failed', 'ignored', 'dead_letter')",
            name="ck_integration_event_status",
        ),
    )

    op.create_index(
        "ix_integration_event_company_received",
        "integration_event",
        ["company_id", "received_at"],
    )
    op.create_index(
        "ix_integration_event_status_received",
        "integration_event",
        ["status", "received_at"],
    )
    op.create_index(
        "ix_integration_event_status_lease",
        "integration_event",
        ["status", "processing_lease_expires_at"],
    )
    op.create_index(
        "ix_integration_event_status_retry",
        "integration_event",
        ["status", "next_attempt_at", "received_at"],
    )

    op.create_index(
        "uq_integration_event_connection_external",
        "integration_event",
        ["integration_id", "external_event_id"],
        unique=True,
        postgresql_where=sa.text("external_event_id IS NOT NULL"),
        sqlite_where=sa.text("external_event_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "uq_integration_event_connection_external",
        table_name="integration_event",
    )
    op.drop_index(
        "ix_integration_event_status_retry",
        table_name="integration_event",
    )
    op.drop_index(
        "ix_integration_event_status_lease",
        table_name="integration_event",
    )

    op.drop_index(
        "ix_integration_event_status_received",
        table_name="integration_event",
    )
    op.drop_index(
        "ix_integration_event_company_received",
        table_name="integration_event",
    )
    op.drop_table("integration_event")

    op.drop_index(
        "uq_company_integration_platform_provider_env",
        table_name="company_integration",
    )
    op.drop_index(
        "uq_company_integration_company_provider_env",
        table_name="company_integration",
    )
    op.drop_index(
        "ix_company_integration_provider_status",
        table_name="company_integration",
    )
    op.drop_index(
        "ix_company_integration_company_status",
        table_name="company_integration",
    )
    op.drop_table("company_integration")

    op.drop_index(
        "ix_integration_provider_category_enabled",
        table_name="integration_provider",
    )
    op.drop_table("integration_provider")
