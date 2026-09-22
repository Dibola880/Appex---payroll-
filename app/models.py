from datetime import datetime, timedelta
from . import db


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)

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
        backref="company",
        lazy=True,
        cascade="all, delete-orphan"
    )

    employees = db.relationship(
        "Employee",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan"
    )

    payroll_runs = db.relationship(
        "PayrollRun",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan"
    )


class User(db.Model):
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
        nullable=False,
        unique=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(50),
        nullable=False,
        default="employee"
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    employee = db.relationship(
        "Employee",
        backref="user",
        uselist=False
    )


class Employee(db.Model):
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

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    invitations = db.relationship(
        "EmployeeInvitation",
        backref="employee",
        lazy=True,
        cascade="all, delete-orphan"
    )

    payslips = db.relationship(
        "Payslip",
        backref="employee",
        lazy=True,
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
        nullable=False,
        unique=True
    )

    expires_at = db.Column(
        db.DateTime,
        nullable=False
    )

    used = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
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
        db.String(50),
        nullable=False
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

    total_net = db.Column(
        db.Float,
        default=0
    )

    deel_payroll_id = db.Column(
        db.String(200)
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    payslips = db.relationship(
        "Payslip",
        backref="payroll_run",
        lazy=True,
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
        nullable=True
    )

    pay_period = db.Column(
        db.String(50)
    )

    pay_date = db.Column(
        db.Date
    )

    gross_pay = db.Column(
        db.Float,
        default=0
    )

    net_pay = db.Column(
        db.Float,
        default=0
    )

    pdf_url = db.Column(
        db.String(500)
    )

    deel_payslip_id = db.Column(
        db.String(200)
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
