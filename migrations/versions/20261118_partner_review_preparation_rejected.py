"""Allow adapter preparation refusal as a terminal review outcome."""

from alembic import op
import sqlalchemy as sa


revision = "p10_partner_review_rejection_01"
down_revision = "p10_payroll_journal_source_01"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("partner_service_request_review") as batch_op:
        batch_op.drop_constraint(
            "ck_partner_request_review_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_status",
            "status IN ('pending', 'approved', 'rejected', 'expired', "
            "'prepared', 'preparation_rejected')",
        )

    with op.batch_alter_table("partner_service_request_review_event") as batch_op:
        batch_op.drop_constraint(
            "ck_partner_request_review_event_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_type",
            "event_type IN ('submitted', 'approved', 'rejected', "
            "'expired', 'prepared', 'preparation_rejected')",
        )
        batch_op.drop_constraint(
            "ck_partner_request_review_event_to_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_to_status",
            "to_status IN ('pending', 'approved', 'rejected', "
            "'expired', 'prepared', 'preparation_rejected')",
        )
        batch_op.drop_constraint(
            "ck_partner_request_review_event_from_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_from_status",
            "from_status IS NULL OR from_status IN "
            "('pending', 'approved', 'rejected', 'expired', "
            "'prepared', 'preparation_rejected')",
        )


def downgrade():
    connection = op.get_bind()

    review_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM partner_service_request_review "
            "WHERE status = 'preparation_rejected'"
        )
    ).scalar_one()

    event_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM partner_service_request_review_event "
            "WHERE event_type = 'preparation_rejected' "
            "OR to_status = 'preparation_rejected' "
            "OR from_status = 'preparation_rejected'"
        )
    ).scalar_one()

    if review_count or event_count:
        raise RuntimeError(
            "Cannot downgrade: preparation-rejected review records or events exist."
        )

    with op.batch_alter_table("partner_service_request_review_event") as batch_op:
        batch_op.drop_constraint(
            "ck_partner_request_review_event_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_type",
            "event_type IN ('submitted', 'approved', 'rejected', 'expired', 'prepared')",
        )
        batch_op.drop_constraint(
            "ck_partner_request_review_event_to_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_to_status",
            "to_status IN ('pending', 'approved', 'rejected', 'expired', 'prepared')",
        )
        batch_op.drop_constraint(
            "ck_partner_request_review_event_from_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_event_from_status",
            "from_status IS NULL OR from_status IN "
            "('pending', 'approved', 'rejected', 'expired', 'prepared')",
        )

    with op.batch_alter_table("partner_service_request_review") as batch_op:
        batch_op.drop_constraint(
            "ck_partner_request_review_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_partner_request_review_status",
            "status IN ('pending', 'approved', 'rejected', 'expired', 'prepared')",
        )
