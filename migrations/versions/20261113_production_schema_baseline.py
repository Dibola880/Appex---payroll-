"""Historical baseline matching the inspected Appex production schema.

Revision ID: p6_prod_base_01
Revises:
Create Date: 2026-11-13

This is a baseline for a fresh database. It is NOT intended to be
applied to the existing production database as an ordinary upgrade.
Production adoption/stamping requires a separate, explicitly approved step.

The schema represented here is the inspected production schema, not the
current SQLAlchemy model metadata. In particular, payslip.pay_period is
nullable in this historical baseline.
"""

from alembic import op
import sqlalchemy as sa


revision = "p6_prod_base_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Core tenant table.
    op.create_table(
        "company",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("payroll_provider", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("contact_person", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column("client_status", sa.String(length=50), nullable=True),
        sa.Column("subscription_plan", sa.String(length=100), nullable=True),
        sa.Column("subscription_status", sa.String(length=50), nullable=True),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=True),
        sa.Column("referral_code", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id", name="company_pkey"),
    )

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="user_company_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="user_pkey"),
        sa.UniqueConstraint("email", name="user_email_key"),
    )

    op.create_table(
        "employee",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_number", sa.String(length=100), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("job_title", sa.String(length=200), nullable=True),
        sa.Column("monthly_salary", sa.Float(precision=53), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("deel_employee_id", sa.String(length=200), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="employee_company_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="employee_user_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="employee_pkey"),
    )

    op.create_table(
        "employee_invitation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employee.id"],
            name="employee_invitation_employee_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="employee_invitation_pkey"),
        sa.UniqueConstraint("token", name="employee_invitation_token_key"),
    )

    op.create_table(
        "loan_product",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("minimum_amount", sa.Float(precision=53), nullable=False),
        sa.Column("maximum_amount", sa.Float(precision=53), nullable=False),
        sa.Column("interest_rate", sa.Float(precision=53), nullable=False),
        sa.Column("repayment_term_months", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="loan_product_company_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="loan_product_pkey"),
    )

    op.create_table(
        "loan_application",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=50), nullable=False),
        sa.Column("requested_amount", sa.Float(precision=53), nullable=False),
        sa.Column("approved_amount", sa.Float(precision=53), nullable=True),
        sa.Column("loan_purpose", sa.String(length=255), nullable=True),
        sa.Column("repayment_term", sa.String(length=100), nullable=True),
        sa.Column("monthly_income", sa.Float(precision=53), nullable=True),
        sa.Column("monthly_expenses", sa.Float(precision=53), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("approval_notes", sa.Text(), nullable=True),
        sa.Column("disbursed_at", sa.DateTime(), nullable=True),
        sa.Column("disbursement_reference", sa.String(length=100), nullable=True),
        sa.Column("total_repayable", sa.Float(precision=53), nullable=True),
        sa.Column("total_paid", sa.Float(precision=53), nullable=True),
        sa.Column("outstanding_balance", sa.Float(precision=53), nullable=True),
        sa.Column("next_payment_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employee.id"], name="loan_application_employee_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["user.id"], name="loan_application_reviewed_by_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["loan_product.id"],
            name="fk_loan_application_product",
        ),
        sa.PrimaryKeyConstraint("id", name="loan_application_pkey"),
    )

    op.create_table(
        "payroll_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("pay_period", sa.String(length=50), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("total_gross", sa.Float(precision=53), nullable=True),
        sa.Column("total_net", sa.Float(precision=53), nullable=True),
        sa.Column("deel_payroll_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column(
            "total_deductions",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "total_employer_uif",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "total_employer_cost",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name="payroll_run_company_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="payroll_run_pkey"),
    )

    op.create_table(
        "payroll_input",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("basic_salary", sa.Float(precision=53), nullable=True),
        sa.Column("overtime", sa.Float(precision=53), nullable=True),
        sa.Column("bonus", sa.Float(precision=53), nullable=True),
        sa.Column("commission", sa.Float(precision=53), nullable=True),
        sa.Column("other_earnings", sa.Float(precision=53), nullable=True),
        sa.Column("other_deductions", sa.Float(precision=53), nullable=True),
        sa.Column(
            "loan_repayment",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employee.id"], name="payroll_input_employee_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.id"],
            name="payroll_input_payroll_run_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="payroll_input_pkey"),
    )

    op.create_table(
        "payslip",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), nullable=True),
        # Historical production definition: nullable, despite the newer ORM model.
        sa.Column("pay_period", sa.String(length=50), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("gross_pay", sa.Float(precision=53), nullable=True),
        sa.Column("net_pay", sa.Float(precision=53), nullable=True),
        sa.Column("pdf_url", sa.String(length=500), nullable=True),
        sa.Column("deel_payslip_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column(
            "basic_salary",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "other_earnings",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "tax_deductions",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "other_deductions",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "total_deductions",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "overtime",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "bonus",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "commission",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "uif",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "employer_uif",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "employer_cost",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.Column(
            "loan_repayment",
            sa.Float(precision=53),
            server_default=sa.text("0"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employee.id"], name="payslip_employee_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.id"],
            name="payslip_payroll_run_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="payslip_pkey"),
    )

    op.create_table(
        "loan_repayment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("loan_application_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), nullable=True),
        sa.Column("payslip_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(precision=53), nullable=False),
        sa.Column("repayment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["loan_application_id"],
            ["loan_application.id"],
            name="loan_repayment_loan_application_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employee.id"], name="loan_repayment_employee_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.id"],
            name="loan_repayment_payroll_run_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["payslip_id"], ["payslip.id"], name="loan_repayment_payslip_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="loan_repayment_pkey"),
    )

    op.create_table(
        "sales_lead",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("contact_person", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("number_of_employees", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("converted_company_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_to"], ["user.id"], name="sales_lead_assigned_to_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["converted_company_id"],
            ["company.id"],
            name="sales_lead_converted_company_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="sales_lead_pkey"),
    )

    op.create_table(
        "client_referral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referrer_company_id", sa.Integer(), nullable=False),
        sa.Column("referred_company_name", sa.String(length=200), nullable=False),
        sa.Column("referred_contact_person", sa.String(length=200), nullable=False),
        sa.Column("referred_email", sa.String(length=200), nullable=False),
        sa.Column("referred_phone", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("converted_company_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["referrer_company_id"],
            ["company.id"],
            name="client_referral_referrer_company_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["converted_company_id"],
            ["company.id"],
            name="client_referral_converted_company_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="client_referral_pkey"),
    )

    # Explicit production indexes. Primary-key and UNIQUE-constraint indexes
    # are created by their constraints above.
    op.create_index(
        "ix_client_referral_referrer_company_id",
        "client_referral",
        ["referrer_company_id"],
        unique=False,
    )
    op.create_index(
        "ix_client_referral_status",
        "client_referral",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_company_referral_code_unique",
        "company",
        ["referral_code"],
        unique=True,
        postgresql_where=sa.text("referral_code IS NOT NULL"),
        sqlite_where=sa.text("referral_code IS NOT NULL"),
    )
    op.create_index(
        "ix_employee_user_id_unique",
        "employee",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
        sqlite_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_loan_application_employee_id",
        "loan_application",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_application_product_id",
        "loan_application",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_application_reference",
        "loan_application",
        ["reference"],
        unique=True,
    )
    op.create_index(
        "ix_loan_application_status",
        "loan_application",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_loan_product_company_id",
        "loan_product",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_repayment_employee_id",
        "loan_repayment",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_repayment_loan_application_id",
        "loan_repayment",
        ["loan_application_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_repayment_payroll_run_id",
        "loan_repayment",
        ["payroll_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_repayment_payslip_id",
        "loan_repayment",
        ["payslip_id"],
        unique=False,
    )
    op.create_index(
        "ix_loan_repayment_reference",
        "loan_repayment",
        ["reference"],
        unique=True,
    )
    op.create_index(
        "ix_sales_lead_status",
        "sales_lead",
        ["status"],
        unique=False,
    )


def downgrade():
    # Reverse dependency order. This downgrade is for disposable/fresh
    # databases only; do not run against production data.
    op.drop_table("client_referral")
    op.drop_table("sales_lead")
    op.drop_table("loan_repayment")
    op.drop_table("payslip")
    op.drop_table("payroll_input")
    op.drop_table("payroll_run")
    op.drop_table("loan_application")
    op.drop_table("employee_invitation")
    op.drop_table("loan_product")
    op.drop_table("employee")
    op.drop_table("user")
    op.drop_table("company")
