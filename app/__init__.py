import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")

    db_url = os.getenv("DATABASE_URL", "sqlite:///appex.db")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        from . import models
        db.create_all()
        seed_demo_data()

    return app

def seed_demo_data():
    from .models import Company, Employee

    if Company.query.count() == 0:
        company = Company(
            name="Appex Financial Institute",
            registration_number="",
            payroll_provider="Deel Local Payroll"
        )

        db.session.add(company)
        db.session.flush()

        demo = [
            Employee(
                company_id=company.id,
                employee_number="EMP001",
                first_name="Demo",
                last_name="Employee",
                email="employee@example.com",
                job_title="Administrator",
                monthly_salary=18500,
                status="Active"
            ),
            Employee(
                company_id=company.id,
                employee_number="EMP002",
                first_name="Sample",
                last_name="Employee",
                email="sample@example.com",
                job_title="Finance Clerk",
                monthly_salary=15000,
                status="Active"
            )
        ]

        db.session.add_all(demo)
        db.session.commit()
