import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import text


db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)

    # ============================================================
    # APPLICATION CONFIGURATION
    # ============================================================

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///appex_payroll.db"
    )

    # Render/PostgreSQL compatibility
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ============================================================
    # SESSION SECURITY
    # ============================================================

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # ============================================================
    # INITIALIZE EXTENSIONS
    # ============================================================

    db.init_app(app)
    migrate.init_app(app, db)

    # ============================================================
    # REGISTER ROUTES
    # ============================================================

    from .routes import bp

    app.register_blueprint(bp)

    # ============================================================
    # DATABASE SETUP / SAFE UPDATES
    # ============================================================

    with app.app_context():

        # Import models so SQLAlchemy knows about all tables
        # before db.create_all() is executed.
        from . import models

        # --------------------------------------------------------
        # Create tables that do not already exist
        # --------------------------------------------------------

        db.create_all()

        # --------------------------------------------------------
        # PostgreSQL-specific safe database updates
        # --------------------------------------------------------

        if db.engine.dialect.name == "postgresql":

            with db.engine.begin() as connection:

                # =================================================
                # EMPLOYEE TABLE
                # =================================================

                connection.execute(text("""
                    ALTER TABLE employee
                    ADD COLUMN IF NOT EXISTS user_id INTEGER
                    REFERENCES "user"(id)
                """))

                connection.execute(text("""
                    ALTER TABLE employee
                    ADD COLUMN IF NOT EXISTS deel_employee_id
                    VARCHAR(200)
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

                # =================================================
                # PAYROLL RUN TABLE
                # =================================================

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

                # =================================================
                # PAYROLL INPUT TABLE
                # =================================================

                connection.execute(text("""
                    ALTER TABLE payroll_input
                    ADD COLUMN IF NOT EXISTS loan_repayment
                    DOUBLE PRECISION DEFAULT 0
                """))

                # =================================================
                # PAYSLIP TABLE
                # =================================================

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

                # -------------------------------------------------
                # Phase 5A
                # Employee loan repayment on payslip
                # -------------------------------------------------

                connection.execute(text("""
                    ALTER TABLE payslip
                    ADD COLUMN IF NOT EXISTS loan_repayment
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

                # =================================================
                # CLIENT ACQUISITION
                # COMPANY TABLE
                # =================================================

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS contact_person
                    VARCHAR(200)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS contact_phone
                    VARCHAR(50)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS contact_email
                    VARCHAR(200)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS client_status
                    VARCHAR(50)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS subscription_plan
                    VARCHAR(100)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS subscription_status
                    VARCHAR(50)
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS onboarding_completed
                    BOOLEAN
                """))

                connection.execute(text("""
                    ALTER TABLE company
                    ADD COLUMN IF NOT EXISTS referral_code
                    VARCHAR(50)
                """))

                # -------------------------------------------------
                # Give existing companies safe default values
                # -------------------------------------------------

                connection.execute(text("""
                    UPDATE company
                    SET client_status = 'Trial'
                    WHERE client_status IS NULL
                """))

                connection.execute(text("""
                    UPDATE company
                    SET subscription_plan = 'Free Trial'
                    WHERE subscription_plan IS NULL
                """))

                connection.execute(text("""
                    UPDATE company
                    SET subscription_status = 'Trial'
                    WHERE subscription_status IS NULL
                """))

                connection.execute(text("""
                    UPDATE company
                    SET onboarding_completed = FALSE
                    WHERE onboarding_completed IS NULL
                """))

                # -------------------------------------------------
                # Referral code index
                # -------------------------------------------------

                connection.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    ix_company_referral_code_unique
                    ON company(referral_code)
                    WHERE referral_code IS NOT NULL
                """))

                # =================================================
                # Phase 5B
                # LOAN PRODUCT
                # =================================================

                # The loan_product table itself is created by
                # db.create_all() from the LoanProduct model.

                # =================================================
                # PHASE 5B
                # LOAN APPLICATION PRODUCT
                # =================================================

                connection.execute(text("""
                    ALTER TABLE loan_application
                    ADD COLUMN IF NOT EXISTS product_id INTEGER
                """))

                # -------------------------------------------------
                # Foreign key
                #
                # Only create it if it does not already exist.
                # -------------------------------------------------

                connection.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname =
                                'fk_loan_application_product'
                        ) THEN

                            ALTER TABLE loan_application
                            ADD CONSTRAINT
                                fk_loan_application_product
                            FOREIGN KEY (product_id)
                            REFERENCES loan_product(id);

                        END IF;
                    END
                    $$;
                """))

                # -------------------------------------------------
                # Index
                # -------------------------------------------------

                connection.execute(text("""
                    CREATE INDEX IF NOT EXISTS
                    ix_loan_application_product_id
                    ON loan_application(product_id)
                """))

    # ============================================================
    # RETURN APPLICATION
    # ============================================================

    return app
