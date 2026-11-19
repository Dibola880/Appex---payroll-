"""Widen partner review event reason codes to 100 characters."""

from alembic import op
import sqlalchemy as sa


revision = "p10_partner_reason_100_01"
down_revision = "p10_partner_review_rejection_01"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "partner_service_request_review_event"
    ) as batch_op:
        batch_op.alter_column(
            "reason_code",
            existing_type=sa.String(length=80),
            type_=sa.String(length=100),
            existing_nullable=True,
        )


def downgrade():
    connection = op.get_bind()
    long_reason_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) "
            "FROM partner_service_request_review_event "
            "WHERE reason_code IS NOT NULL "
            "AND length(reason_code) > 80"
        )
    ).scalar_one()

    if long_reason_count:
        raise RuntimeError(
            "Cannot downgrade: partner review event reason codes "
            "longer than 80 characters exist."
        )

    with op.batch_alter_table(
        "partner_service_request_review_event"
    ) as batch_op:
        batch_op.alter_column(
            "reason_code",
            existing_type=sa.String(length=100),
            type_=sa.String(length=80),
            existing_nullable=True,
        )
