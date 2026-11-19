"""Add prepared payroll disbursement batches and instructions.

Revision ID: p8_payroll_disb_01
Revises: p8_payment_recon_01
"""

from alembic import op
import sqlalchemy as sa


revision = "p8_payroll_disb_01"
down_revision = "p8_payment_recon_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payroll_disbursement_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payroll_run_id",
            sa.Integer(),
            sa.ForeignKey("payroll_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            sa.Integer(),
            sa.ForeignKey("company_integration.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("instruction_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="prepared",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('prepared', 'cancelled')",
            name="ck_payroll_disbursement_batch_status",
        ),
        sa.CheckConstraint(
            "total_amount > 0",
            name="ck_payroll_disbursement_batch_positive_total",
        ),
        sa.CheckConstraint(
            "instruction_count > 0",
            name="ck_payroll_disbursement_batch_positive_count",
        ),
        sa.UniqueConstraint(
            "payroll_run_id",
            name="uq_payroll_disbursement_batch_payroll_run",
        ),
    )

    op.create_index(
        "ix_payroll_disbursement_batch_company_status",
        "payroll_disbursement_batch",
        ["company_id", "status"],
    )

    op.create_table(
        "payroll_disbursement_instruction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey(
                "payroll_disbursement_batch.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "payslip_id",
            sa.Integer(),
            sa.ForeignKey("payslip.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employee.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_payroll_disbursement_instruction_positive_amount",
        ),
        sa.UniqueConstraint(
            "payslip_id",
            name="uq_payroll_disbursement_instruction_payslip",
        ),
    )

    op.create_index(
        "ix_payroll_disbursement_instruction_batch",
        "payroll_disbursement_instruction",
        ["batch_id"],
    )


def downgrade():
    op.drop_index(
        "ix_payroll_disbursement_instruction_batch",
        table_name="payroll_disbursement_instruction",
    )
    op.drop_table("payroll_disbursement_instruction")

    op.drop_index(
        "ix_payroll_disbursement_batch_company_status",
        table_name="payroll_disbursement_batch",
    )
    op.drop_table("payroll_disbursement_batch")
