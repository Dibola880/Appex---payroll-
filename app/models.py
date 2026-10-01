from datetime import datetime

from . import db


# ============================================================
# COMPANY
# ============================================================

class Company(db.Model):
    __tablename__ = "company"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    registration_number = db.Column(
        db.String(100)
    )

    payroll_provider = db.Column(
        db.String(100),
        default="Deel Local Payroll"
    )

    # ========================================================
    # CLIENT ACQUISITION / ONBOARDING
    # ========================================================

    contact_person = db.Column(
        db.String(200)
    )

    contact_phone = db.Column(
        db.String(50)
    )

    contact_email = db.Column(
        db.String(200)
    )

    client_status = db.Column(
        db.String(50),
        default="Trial"
    )

    subscription_plan = db.Column(
        db.String(100),
        default="Free Trial"
    )

    subscription_status = db.Column(
        db.String(50),
        default="Trial"
    )

    onboarding_completed = db.Column(
        db.Boolean,
        default=False
    )

    referral_code = db.Column(
        db.String(50),
        unique=True,
        nullable=True,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    users = db.relationship(
        "User",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    employees = db.relationship(
        "Employee",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    payroll_runs = db.relationship(
        "PayrollRun",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    loan_products = db.relationship(
        "LoanProduct",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    sales_leads = db.relationship(
        "SalesLead",
        foreign_keys="SalesLead.converted_company_id",
        back_populates="converted_company"
    )

    referrals_made = db.relationship(
        "ClientReferral",
        foreign_keys="ClientReferral.referrer_company_id",
        back_populates="referrer_company",
        cascade="all, delete-orphan"
    )

    referrals_received = db.relationship(
        "ClientReferral",
        foreign_keys="ClientReferral.converted_company_id",
        back_populates="converted_company"
    )


# ============================================================
# USER
# ============================================================

class User(db.Model):
    __tablename__ = "user"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(200),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(50),
        default="employee"
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    company = db.relationship(
        "Company",
        back_populates="users"
    )

    employee = db.relationship(
        "Employee",
        back_populates="user",
        uselist=False
    )


# ============================================================
# EMPLOYEE
# ============================================================

class Employee(db.Model):
    __tablename__ = "employee"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    employee_number = db.Column(
        db.String(100)
    )

    first_name = db.Column(
        db.String(100),
        nullable=False
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    date_of_birth = db.Column(
        db.Date,
        nullable=True
    )

    email = db.Column(
        db.String(200)
    )

    job_title = db.Column(
        db.String(200)
    )

    monthly_salary = db.Column(
        db.Float,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="Active"
    )

    deel_employee_id = db.Column(
        db.String(200)
    )

    company = db.relationship(
        "Company",
        back_populates="employees"
    )

    user = db.relationship(
        "User",
        back_populates="employee"
    )

    invitations = db.relationship(
        "EmployeeInvitation",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    payroll_inputs = db.relationship(
        "PayrollInput",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    loan_applications = db.relationship(
        "LoanApplication",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    loan_repayments = db.relationship(
        "LoanRepayment",
        back_populates="employee",
        cascade="all, delete-orphan"
    )


# ============================================================
# EMPLOYEE INVITATION
# ============================================================

class EmployeeInvitation(db.Model):
    __tablename__ = "employee_invitation"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    token = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=False
    )

    used = db.Column(
        db.Boolean,
        default=False
    )

    employee = db.relationship(
        "Employee",
        back_populates="invitations"
    )

    def is_valid(self):
        return (
            not self.used
            and self.expires_at > datetime.utcnow()
        )


# ============================================================
# PAYROLL RUN
# ============================================================

class PayrollRun(db.Model):
    __tablename__ = "payroll_run"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    pay_period = db.Column(
        db.String(100)
    )

    pay_date = db.Column(
        db.Date
    )

    status = db.Column(
        db.String(50),
        default="Draft"
    )

    total_gross = db.Column(
        db.Float,
        default=0
    )

    total_deductions = db.Column(
        db.Float,
        default=0
    )

    total_net = db.Column(
        db.Float,
        default=0
    )

    total_employer_uif = db.Column(
        db.Float,
        default=0
    )

    total_employer_cost = db.Column(
        db.Float,
        default=0
    )

    deel_payroll_id = db.Column(
        db.String(200)
    )

    company = db.relationship(
        "Company",
        back_populates="payroll_runs"
    )

    payroll_inputs = db.relationship(
        "PayrollInput",
        back_populates="payroll_run",
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        back_populates="payroll_run",
        cascade="all, delete-orphan"
    )

    loan_repayments = db.relationship(
        "LoanRepayment",
        back_populates="payroll_run"
    )


# ============================================================
# PAYROLL INPUT
# ============================================================

class PayrollInput(db.Model):
    __tablename__ = "payroll_input"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=False,
        index=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    basic_salary = db.Column(
        db.Float,
        default=0
    )

    overtime = db.Column(
        db.Float,
        default=0
    )

    bonus = db.Column(
        db.Float,
        default=0
    )

    commission = db.Column(
        db.Float,
        default=0
    )

    other_earnings = db.Column(
        db.Float,
        default=0
    )

    other_deductions = db.Column(
        db.Float,
        default=0
    )

    loan_repayment = db.Column(
        db.Float,
        default=0
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="payroll_inputs"
    )

    employee = db.relationship(
        "Employee",
        back_populates="payroll_inputs"
    )


# ============================================================
# PAYSLIP
# ============================================================

class Payslip(db.Model):
    __tablename__ = "payslip"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=False
    )

    pay_period = db.Column(
        db.String(100)
    )

    pay_date = db.Column(
        db.Date
    )

    basic_salary = db.Column(
        db.Float,
        default=0
    )

    overtime = db.Column(
        db.Float,
        default=0
    )

    bonus = db.Column(
        db.Float,
        default=0
    )

    commission = db.Column(
        db.Float,
        default=0
    )

    other_earnings = db.Column(
        db.Float,
        default=0
    )

    gross_pay = db.Column(
        db.Float,
        default=0
    )

    tax_deductions = db.Column(
        db.Float,
        default=0
    )

    uif = db.Column(
        db.Float,
        default=0
    )

    other_deductions = db.Column(
        db.Float,
        default=0
    )

    loan_repayment = db.Column(
        db.Float,
        default=0
    )

    total_deductions = db.Column(
        db.Float,
        default=0
    )

    net_pay = db.Column(
        db.Float,
        default=0
    )

    employer_uif = db.Column(
        db.Float,
        default=0
    )

    employer_cost = db.Column(
        db.Float,
        default=0
    )

    deel_payslip_id = db.Column(
        db.String(200)
    )

    pdf_url = db.Column(
        db.String(500)
    )

    employee = db.relationship(
        "Employee",
        back_populates="payslips"
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="payslips"
    )


# ============================================================
# LOAN PRODUCT
# ============================================================

class LoanProduct(db.Model):
    __tablename__ = "loan_product"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
        index=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    minimum_amount = db.Column(
        db.Float,
        default=500,
        nullable=False
    )

    maximum_amount = db.Column(
        db.Float,
        default=3000,
        nullable=False
    )

    interest_rate = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    service_fee = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    repayment_term_months = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    max_deduction_percent = db.Column(
        db.Float,
        default=30,
        nullable=False
    )

    minimum_employment_months = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    company = db.relationship(
        "Company",
        back_populates="loan_products"
    )

    loan_applications = db.relationship(
        "LoanApplication",
        back_populates="loan_product"
    )


# ============================================================
# LOAN APPLICATION
# ============================================================

class LoanApplication(db.Model):
    __tablename__ = "loan_application"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_product.id"),
        nullable=True,
        index=True
    )

    reference = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    requested_amount = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    approved_amount = db.Column(
        db.Float,
        nullable=True
    )

    loan_purpose = db.Column(
        db.String(255)
    )

    repayment_term = db.Column(
        db.String(100)
    )

    monthly_income = db.Column(
        db.Float,
        default=0
    )

    monthly_expenses = db.Column(
        db.Float,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="Submitted",
        nullable=False,
        index=True
    )

    reviewed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    reviewed_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    approval_notes = db.Column(
        db.Text,
        nullable=True
    )

    disbursed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    disbursement_reference = db.Column(
        db.String(100),
        nullable=True
    )

    total_repayable = db.Column(
        db.Float,
        nullable=True
    )

    total_paid = db.Column(
        db.Float,
        default=0
    )

    outstanding_balance = db.Column(
        db.Float,
        default=0
    )

    next_payment_date = db.Column(
        db.Date,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    employee = db.relationship(
        "Employee",
        back_populates="loan_applications"
    )

    loan_product = db.relationship(
        "LoanProduct",
        back_populates="loan_applications"
    )

    reviewer = db.relationship(
        "User",
        foreign_keys=[reviewed_by]
    )

    repayments = db.relationship(
        "LoanRepayment",
        back_populates="loan_application",
        cascade="all, delete-orphan"
    )


# ============================================================
# LOAN REPAYMENT LEDGER
# ============================================================

class LoanRepayment(db.Model):
    __tablename__ = "loan_repayment"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    loan_application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_application.id"),
        nullable=False,
        index=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    payroll_run_id = db.Column(
        db.Integer,
        db.ForeignKey("payroll_run.id"),
        nullable=True,
        index=True
    )

    payslip_id = db.Column(
        db.Integer,
        db.ForeignKey("payslip.id"),
        nullable=True,
        index=True
    )

    amount = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    repayment_date = db.Column(
        db.Date,
        default=lambda: datetime.utcnow().date(),
        nullable=False
    )

    payment_method = db.Column(
        db.String(50),
        default="Payroll Deduction",
        nullable=False
    )

    reference = db.Column(
        db.String(100),
        unique=True,
        nullable=True,
        index=True
    )

    status = db.Column(
        db.String(50),
        default="Completed",
        nullable=False
    )

    notes = db.Column(
        db.Text,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    loan_application = db.relationship(
        "LoanApplication",
        back_populates="repayments"
    )

    employee = db.relationship(
        "Employee",
        back_populates="loan_repayments"
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="loan_repayments"
    )

    payslip = db.relationship(
        "Payslip"
    )


# ============================================================
# SALES LEAD
# ============================================================

class SalesLead(db.Model):
    __tablename__ = "sales_lead"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    company_name = db.Column(
        db.String(200),
        nullable=False
    )

    registration_number = db.Column(
        db.String(100),
        nullable=True
    )

    contact_person = db.Column(
        db.String(200),
        nullable=False
    )

    email = db.Column(
        db.String(200),
        nullable=False
    )

    phone = db.Column(
        db.String(50),
        nullable=True
    )

    number_of_employees = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="New Lead",
        nullable=False,
        index=True
    )

    source = db.Column(
        db.String(100),
        default="Direct",
        nullable=False
    )

    notes = db.Column(
        db.Text,
        nullable=True
    )

    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    converted_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    assigned_user = db.relationship(
        "User",
        foreign_keys=[assigned_to]
    )

    converted_company = db.relationship(
        "Company",
        foreign_keys=[converted_company_id],
        back_populates="sales_leads"
    )


# ============================================================
# CLIENT REFERRAL
# ============================================================

class ClientReferral(db.Model):
    __tablename__ = "client_referral"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    referrer_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
        index=True
    )

    referred_company_name = db.Column(
        db.String(200),
        nullable=False
    )

    referred_contact_person = db.Column(
        db.String(200),
        nullable=False
    )

    referred_email = db.Column(
        db.String(200),
        nullable=False
    )

    referred_phone = db.Column(
        db.String(50),
        nullable=True
    )

    status = db.Column(
        db.String(50),
        default="Submitted",
        nullable=False,
        index=True
    )

    converted_company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    referrer_company = db.relationship(
        "Company",
        foreign_keys=[referrer_company_id],
        back_populates="referrals_made"
    )

    converted_company = db.relationship(
        "Company",
        foreign_keys=[converted_company_id],
        back_populates="referrals_received"
    )
