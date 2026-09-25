from datetime import datetime
from . import db


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    registration_number = db.Column(db.String(100))
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


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

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
        default="employee",
        nullable=False
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


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        unique=True,
        nullable=True
    )

    employee_number = db.Column(
        db.String(100),
        nullable=False
    )

    first_name = db.Column(
        db.String(100),
        nullable=False
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    date_of_birth = db.Column(db.Date)

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
        backref="employee",
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        backref="employee",
        cascade="all, delete-orphan"
    )


class EmployeeInvitation(db.Model):
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

    def is_valid(self):
        return (
            not self.used
            and datetime.utcnow() < self.expires_at
        )


class PayrollRun(db.Model):
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
        db.String(100),
        nullable=False
    )

    pay_date = db.Column(
        db.Date,
        nullable=False
    )

    status = db.Column(
        db.String(50),
        default="Processing"
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

    # Employer statutory contribution
    total_employer_uif = db.Column(
        db.Float,
        default=0
    )

    # Gross payroll + employer UIF
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
        backref="payroll_run",
        cascade="all, delete-orphan"
    )


class Payslip(db.Model):
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
        db.String(100),
        nullable=False
    )

    pay_date = db.Column(
        db.Date,
        nullable=False
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

    # Employer UIF contribution
    employer_uif = db.Column(
        db.Float,
        default=0
    )

    # Employee + employer payroll cost information
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
