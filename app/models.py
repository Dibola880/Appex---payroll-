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

    payslips = db.relationship(
        "Payslip",
        back_populates="payroll_run",
        cascade="all, delete-orphan"
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
# LOAN APPLICATION
# ============================================================

class LoanApplication(db.Model):

    __tablename__ = "loan_application"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # Employee relationship

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False,
        index=True
    )

    # Application reference

    reference = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    # Loan information

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

    # Affordability information

    monthly_income = db.Column(
        db.Float,
        default=0
    )

    monthly_expenses = db.Column(
        db.Float,
        default=0
    )

    # Application status

    status = db.Column(
        db.String(50),
        default="Submitted",
        nullable=False,
        index=True
    )

    # Approval information

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

    # Disbursement information

    disbursed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    disbursement_reference = db.Column(
        db.String(100),
        nullable=True
    )

    # Repayment information

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

    # Timestamps

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

    # Relationships

    employee = db.relationship(
        "Employee",
        back_populates="loan_applications"
    )

    reviewer = db.relationship(
        "User",
        foreign_keys=[reviewed_by]
    )
