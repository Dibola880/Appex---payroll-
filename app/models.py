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

    employees = db.relationship(
        "Employee",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("company.id"),
        nullable=False
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

    email = db.Column(db.String(200))
    job_title = db.Column(db.String(200))

    monthly_salary = db.Column(
        db.Float,
        default=0
    )

    status = db.Column(
        db.String(50),
        default="Active"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
