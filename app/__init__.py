import os

from flask import Flask

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from sqlalchemy import text


# ============================================================
# DATABASE
# ============================================================

db = SQLAlchemy()

migrate = Migrate()


# ============================================================
# CREATE APPLICATION
# ============================================================

def create_app():

    app = Flask(__name__)


    # ========================================================
    # SECRET KEY
    # ========================================================

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )


    # ========================================================
    # DATABASE URL
    # ========================================================

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///appex_payroll.db"
    )


    # Render / PostgreSQL compatibility
    if database_url.startswith("postgres://"):

        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )


    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


    # ========================================================
    # SESSION SECURITY
    # ========================================================

    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


    # ========================================================
    # INITIALISE DATABASE
    # ========================================================

    db.init_app(app)

    migrate.init_app(
        app,
        db
    )


    # ========================================================
    # REGISTER ROUTES
    # ========================================================

    from .routes import bp

    app.register_blueprint(bp)


    # ========================================================
    # DATABASE INITIALISATION / MIGRATION
    # ========================================================

    with app.app_context():

        from . import models

        # Create tables that don't already exist
        db.create_all()


        # ====================================================
        # POSTGRESQL DATABASE UPDATES
        # ====================================================

        if db.engine.dialect.name == "postgresql":

            with db.engine.begin() as connection:


                # ------------------------------------------------
                # EMPLOYEE TABLE
                # ------------------------------------------------

                connection.execute(
                    text("""
                        ALTER TABLE employee
                        ADD COLUMN IF NOT EXISTS user_id INTEGER
                        REFERENCES "user"(id)
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE employee
                        ADD COLUMN IF NOT EXISTS deel_employee_id
                        VARCHAR(200)
                    """)
                )


                connection.execute(
                    text("""
                        CREATE UNIQUE INDEX IF NOT EXISTS
                        ix_employee_user_id_unique
                        ON employee(user_id)
                        WHERE user_id IS NOT NULL
                    """)
                )


                # ------------------------------------------------
                # PAYROLL RUN
                # ------------------------------------------------

                connection.execute(
                    text("""
                        ALTER TABLE payroll_run
                        ADD COLUMN IF NOT EXISTS total_deductions
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                # ------------------------------------------------
                # PAYSLIP — EXISTING FIELDS
                # ------------------------------------------------

                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS basic_salary
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS other_earnings
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS tax_deductions
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS other_deductions
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS total_deductions
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                # =================================================
                # NEW PAYSLIP EARNINGS FIELDS
                # =================================================

                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS overtime
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS bonus
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS commission
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                # =================================================
                # NEW PAYSLIP DEDUCTION FIELD
                # =================================================

                connection.execute(
                    text("""
                        ALTER TABLE payslip
                        ADD COLUMN IF NOT EXISTS uif
                        DOUBLE PRECISION DEFAULT 0
                    """)
                )


                # =================================================
                # ENSURE EXISTING NULL VALUES BECOME ZERO
                # =================================================

                connection.execute(
                    text("""
                        UPDATE payslip
                        SET basic_salary = 0
                        WHERE basic_salary IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET overtime = 0
                        WHERE overtime IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET bonus = 0
                        WHERE bonus IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET commission = 0
                        WHERE commission IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET other_earnings = 0
                        WHERE other_earnings IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET tax_deductions = 0
                        WHERE tax_deductions IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET uif = 0
                        WHERE uif IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET other_deductions = 0
                        WHERE other_deductions IS NULL
                    """)
                )


                connection.execute(
                    text("""
                        UPDATE payslip
                        SET total_deductions = 0
                        WHERE total_deductions IS NULL
                    """)
                )


    return app
