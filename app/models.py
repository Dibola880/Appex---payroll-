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

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

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

    # --------------------------------------------------------
    # Phase 5B
    # Loan products belonging to this company
    # --------------------------------------------------------

    loan_products = db.relationship(
        "LoanProduct",
        back_populates="company",
        cascade="all, delete-orphan"
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

    # --------------------------------------------------------
    # Payroll earnings
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Payroll deductions
    # --------------------------------------------------------

    other_deductions = db.Column(
        db.Float,
        default=0
    )

    # --------------------------------------------------------
    # Phase 5A
    # Employee loan repayment deducted through payroll
    # --------------------------------------------------------

    loan_repayment = db.Column(
        db.Float,
        default=0
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Earnings
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Deductions
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Phase 5A
    # Employee loan repayment
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Employer costs
    # --------------------------------------------------------

    employer_uif = db.Column(
        db.Float,
        default=0
    )

    employer_cost = db.Column(
        db.Float,
        default=0
    )

    # --------------------------------------------------------
    # Deel / document fields
    # --------------------------------------------------------

    deel_payslip_id = db.Column(
        db.String(200)
    )

    pdf_url = db.Column(
        db.String(500)
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    employee = db.relationship(
        "Employee",
        back_populates="payslips"
    )

    payroll_run = db.relationship(
        "PayrollRun",
        back_populates="payslips"
    )


# ============================================================
# PHASE 5B
# LOAN PRODUCT
# ============================================================

class LoanProduct(db.Model):

    __tablename__ = "loan_product"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # --------------------------------------------------------
    # Company that owns this loan product
    # --------------------------------------------------------

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False,
        index=True
    )

    # --------------------------------------------------------
    # Product information
    # --------------------------------------------------------

    name = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    # --------------------------------------------------------
    # Loan limits
    # --------------------------------------------------------

    minimum_amount = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    maximum_amount = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    # --------------------------------------------------------
    # Pricing
    #
    # Example:
    # 40.00 means 40%
    # --------------------------------------------------------

    interest_rate = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    # --------------------------------------------------------
    # Repayment
    # --------------------------------------------------------

    repayment_term_months = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    # --------------------------------------------------------
    # Product status
    # --------------------------------------------------------

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    # --------------------------------------------------------
    # Timestamps
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Phase 5B
    # Selected loan product
    #
    # Nullable so existing Phase 5A applications
    # continue working.
    # --------------------------------------------------------

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
        class LoanProduct(db.Model):
    __tablename__ = "loan_product"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    min_amount = db.Column(
        db.Float,
        default=500
    )

    max_amount = db.Column(
        db.Float,
        default=3000
    )

    repayment_term_months = db.Column(
        db.Integer,
        default=1
    )

    interest_rate = db.Column(
        db.Float,
        default=0
    )

    service_fee = db.Column(
        db.Float,
        default=0
    )

    max_deduction_percent = db.Column(
        db.Float,
        default=30
    )

    minimum_employment_months = db.Column(
        db.Integer,
        default=0
    )

    active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    company = db.relationship(
        "Company",
        backref=db.backref(
            "loan_products",
            lazy=True
        )
    )

    def __repr__(self):
        return f"<LoanProduct {self.name}>"
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

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

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
