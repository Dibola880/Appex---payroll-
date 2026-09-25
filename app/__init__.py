import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import text

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///appex_payroll.db"
    )

    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        from . import models

        # Create any tables that do not already exist.
        db.create_all()

        # Safely update the existing PostgreSQL database.
        if db.engine.dialect.name == "postgresql":

            with db.engine.begin() as connection:

                # --------------------------------------------------
                # EMPLOYEE TABLE
                # --------------------------------------------------

                connection.execute(text("""
                    ALTER TABLE employee
                    ADD COLUMN IF NOT EXISTS user_id INTEGER
                    REFERENCES "user"(id)
                """))

                connection.execute(text("""
                    ALTER TABLE employee
                    ADD COLUMN IF NOT EXISTS deel_employee_id VARCHAR(200)
                """))

                connection.execute(text("""
                    ALTER TABLE employee
                    ADD COLUMN IF NOT EXISTS date_of_birth DATE
                """))

                connection.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    ix_employee_user_id_unique
                    ON employee(user_id)
                    WHERE user_id IS NOT NULL
                """))

                # --------------------------------------------------
                # PAYROLL RUN TABLE
                # --------------------------------------------------

                connection.execute(text("""
                    ALTER TABLE payroll_run
                    ADD COLUMN IF NOT EXISTS total_deductions
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payroll_run
                    ADD COLUMN IF NOT EXISTS total_employer_uif
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payroll_run
                    ADD COLUMN IF NOT EXISTS total_employer_cost
                    DOUBLE PRECISION DEFAULT 0
                """))

                # --------------------------------------------------
                # PAYSLIP TABLE
                # --------------------------------------------------

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS basic_salary
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS other_earnings
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS tax_deductions
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS other_deductions
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS total_deductions
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS employer_uif
                    DOUBLE PRECISION DEFAULT 0
                """))

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS employer_cost
                    DOUBLE PRECISION DEFAULT 0
                """))


    return app
