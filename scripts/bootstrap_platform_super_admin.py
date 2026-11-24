"""
Restricted, one-time Appex Platform Super Admin bootstrap.

This script does not create or modify database schema.
It must never be run without separate operator approval.
"""

import argparse
import getpass
import os
import re
import sys


EXPECTED_DATABASE = "appex_payroll_preview"
EXPECTED_EMAIL = "Bonganebeez@yahoo.com"
INTERNAL_COMPANY_NAME = "Appex Platform Operations"
ADMIN_NAME = "Appex Platform Administrator"
MIN_PASSWORD_LENGTH = 14


class BootstrapRefused(RuntimeError):
    pass


def bootstrap_platform_admin(
    app,
    *,
    email,
    password,
    reason,
    expected_database,
    allow_sqlite_for_tests=False,
):
    """Create the internal company, platform administrator and audit event."""

    from sqlalchemy import inspect, text
    from werkzeug.security import generate_password_hash

    from app import db
    from app.models import Company, PlatformAuditLog, User
    from app.platform_audit import record_platform_audit
    from app.roles import PLATFORM_SUPER_ADMIN

    if expected_database != EXPECTED_DATABASE:
        raise BootstrapRefused("The expected database is not on the approved allowlist.")

    if email != EXPECTED_EMAIL:
        raise BootstrapRefused("The administrator email does not match the approved identity.")

    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise BootstrapRefused(
            f"The initial password must contain at least {MIN_PASSWORD_LENGTH} characters."
        )

    if not isinstance(reason, str) or not reason.strip():
        raise BootstrapRefused("A non-empty audit reason is required.")

    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name

        if dialect == "postgresql":
            actual_database = db.session.execute(
                text("SELECT current_database()")
            ).scalar_one()
        elif dialect == "sqlite" and allow_sqlite_for_tests:
            actual_database = os.path.basename(engine.url.database)
        else:
            raise BootstrapRefused(
                "Only PostgreSQL is permitted for real bootstrap execution."
            )

        if actual_database != expected_database:
            raise BootstrapRefused(
                f"Database identity mismatch: expected {expected_database!r}; "
                f"received {actual_database!r}."
            )

        if not inspect(engine).has_table("platform_audit_log"):
            raise BootstrapRefused(
                "The platform_audit_log table is missing. "
                "No schema will be created or changed by this script."
            )

        try:
            if Company.query.filter_by(name=INTERNAL_COMPANY_NAME).first():
                raise BootstrapRefused(
                    "The internal platform company already exists. No changes made."
                )

            if User.query.filter_by(role=PLATFORM_SUPER_ADMIN).first():
                raise BootstrapRefused(
                    "A Platform Super Admin already exists. No changes made."
                )

            if User.query.filter_by(email=email).first():
                raise BootstrapRefused(
                    "The approved administrator email already exists. No changes made."
                )

            company = Company(
                name=INTERNAL_COMPANY_NAME,
                payroll_provider="Internal Operations",
                client_status="Internal",
                subscription_plan="Internal",
                subscription_status="Not Applicable",
                onboarding_completed=True,
                referral_code=None,
            )
            db.session.add(company)
            db.session.flush()

            administrator = User(
                company_id=company.id,
                name=ADMIN_NAME,
                email=email,
                password_hash=generate_password_hash(password),
                role=PLATFORM_SUPER_ADMIN,
                is_active=True,
            )
            db.session.add(administrator)
            db.session.flush()

            record_platform_audit(
                actor=administrator,
                action="platform.bootstrap_created",
                target_type="platform_super_admin",
                target_id=administrator.id,
                company_id=company.id,
                reason=reason.strip(),
                after_data={
                    "email": email,
                    "company_name": INTERNAL_COMPANY_NAME,
                    "role": PLATFORM_SUPER_ADMIN,
                    "bootstrap": True,
                },
            )

            db.session.commit()

            return {
                "company_id": company.id,
                "administrator_id": administrator.id,
                "email": email,
            }

        except Exception:
            db.session.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Restricted Appex Platform Super Admin bootstrap."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize the bootstrap attempt.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason to retain in the platform audit record.",
    )
    args = parser.parse_args()

    if not args.execute:
        raise BootstrapRefused("Missing required --execute confirmation.")

    if os.getenv("APPEX_PLATFORM_BOOTSTRAP_ENABLED") != "1":
        raise BootstrapRefused(
            "APPEX_PLATFORM_BOOTSTRAP_ENABLED must explicitly equal 1."
        )

    if os.getenv("APPEX_PLATFORM_BOOTSTRAP_DATABASE") != EXPECTED_DATABASE:
        raise BootstrapRefused(
            "The explicit database allowlist must equal appex_payroll_preview."
        )

    if not os.getenv("DATABASE_URL"):
        raise BootstrapRefused("DATABASE_URL is not configured.")

    if not os.getenv("SECRET_KEY"):
        raise BootstrapRefused("SECRET_KEY must be configured.")

    # Set startup protections BEFORE importing or creating the Flask app.
    os.environ["APP_ENV"] = "production"
    os.environ["APPEX_SKIP_STARTUP_SCHEMA_UPDATES"] = "true"
    os.environ["APPEX_ALLOW_STARTUP_SCHEMA_UPDATES"] = ""

    from app import create_app

    app = create_app()

    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        raise BootstrapRefused("SQLite is not permitted for real bootstrap execution.")

    password = getpass.getpass("Initial administrator password: ")
    confirmation = getpass.getpass("Confirm initial administrator password: ")

    if password != confirmation:
        raise BootstrapRefused("The passwords do not match.")

    result = bootstrap_platform_admin(
        app,
        email=EXPECTED_EMAIL,
        password=password,
        reason=args.reason,
        expected_database=EXPECTED_DATABASE,
    )

    print("Platform administrator bootstrap completed.")
    print(f"Company ID: {result['company_id']}")
    print(f"Administrator ID: {result['administrator_id']}")
    print(f"Administrator email: {result['email']}")
    print("The password was not displayed or recorded.")


if __name__ == "__main__":
    try:
        main()
    except BootstrapRefused as exc:
        print(f"BOOTSTRAP REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception:
        print(
            "BOOTSTRAP FAILED. The transaction was rolled back. "
            "Inspect the operator-side error logs.",
            file=sys.stderr,
        )
        sys.exit(1)
