"""Isolated tests for the restricted Platform Super Admin bootstrap.

TEST-ONLY:
- Uses disposable SQLite files in temporary directories.
- Verifies the database path before creating tables.
- Never invokes the bootstrap CLI.
- Never connects to Preview or production.
"""

import importlib.util
import os
import tempfile
import sys
from pathlib import Path

from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "bootstrap_platform_super_admin.py"

ENV_KEYS = (
    "DATABASE_URL",
    "SECRET_KEY",
    "APP_ENV",
    "APPEX_SKIP_STARTUP_SCHEMA_UPDATES",
    "APPEX_ALLOW_STARTUP_SCHEMA_UPDATES",
)
OLD_ENV = {key: os.environ.get(key) for key in ENV_KEYS}

results = []


def record(name, passed, details=""):
    results.append((name, bool(passed)))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


def load_bootstrap_module():
    spec = importlib.util.spec_from_file_location(
        "platform_admin_bootstrap_test_module", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    # Configure startup protections before importing the application.
    with tempfile.TemporaryDirectory(prefix="appex_bootstrap_tests_") as temp:
        db_path = Path(temp) / "appex_payroll_preview"

        os.environ["DATABASE_URL"] = "sqlite:///" + str(db_path)
        os.environ["SECRET_KEY"] = "bootstrap-tests-only"
        os.environ["APP_ENV"] = "testing"
        os.environ["APPEX_SKIP_STARTUP_SCHEMA_UPDATES"] = "true"
        os.environ.pop("APPEX_ALLOW_STARTUP_SCHEMA_UPDATES", None)

        from app import create_app, db
        from app.models import (
            Company,
            CompanySubscription,
            PlatformAuditLog,
            User,
        )
        from app.roles import PLATFORM_SUPER_ADMIN

        bootstrap = load_bootstrap_module()
        app = create_app()
        app.config["TESTING"] = True

        with app.app_context():
            actual_path = Path(db.engine.url.database).resolve()
            expected_path = db_path.resolve()
            isolated = (
                db.engine.dialect.name == "sqlite"
                and actual_path == expected_path
            )
            record(
                "Application is connected only to the disposable SQLite file",
                isolated,
                f"dialect={db.engine.dialect.name}; path={actual_path}",
            )
            if not isolated:
                raise RuntimeError("Safety stop: unexpected database connection.")

            # This creates tables only in the verified temporary SQLite database.
            db.create_all()

            approved_email = bootstrap.EXPECTED_EMAIL
            test_password = "TestOnly-Platform-Password-2026!"
            reason = "Isolated automated bootstrap test."

            # 1. Successful atomic bootstrap.
            created = bootstrap.bootstrap_platform_admin(
                app,
                email=approved_email,
                password=test_password,
                reason=reason,
                expected_database=bootstrap.EXPECTED_DATABASE,
                allow_sqlite_for_tests=True,
            )

            company = db.session.get(Company, created["company_id"])
            administrator = db.session.get(User, created["administrator_id"])
            audit = PlatformAuditLog.query.filter_by(
                action="platform.bootstrap_created"
            ).one()

            success_ok = (
                company is not None
                and company.name == bootstrap.INTERNAL_COMPANY_NAME
                and company.payroll_provider == "Internal Operations"
                and company.client_status == "Internal"
                and company.subscription_plan == "Internal"
                and company.subscription_status == "Not Applicable"
                and company.onboarding_completed is True
                and company.referral_code is None
                and administrator is not None
                and administrator.email == approved_email
                and administrator.role == PLATFORM_SUPER_ADMIN
                and administrator.company_id == company.id
                and administrator.is_active is True
                and check_password_hash(
                    administrator.password_hash, test_password
                )
                and audit.actor_user_id == administrator.id
                and audit.actor_role == PLATFORM_SUPER_ADMIN
                and audit.company_id == company.id
                and audit.target_type == "platform_super_admin"
                and audit.reason == reason
                and audit.after_data.get("bootstrap") is True
                and CompanySubscription.query.count() == 0
            )
            record(
                "Successful bootstrap creates internal company, admin and audit atomically without subscription",
                success_ok,
            )

            # 2. Wrong database allowlist is rejected before database work.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password=test_password,
                    reason=reason,
                    expected_database="some_other_database",
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("Wrong expected database is refused", rejected)

            # 3. Wrong email is rejected.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email="someone-else@example.test",
                    password=test_password,
                    reason=reason,
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("Unapproved administrator email is refused", rejected)

            # 4. Weak password is rejected.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password="short",
                    reason=reason,
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("Password shorter than the minimum is refused", rejected)

            # 5. Blank audit reason is rejected.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password=test_password,
                    reason="   ",
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("Blank audit reason is refused", rejected)

            # 6. SQLite is refused unless explicitly enabled for tests.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password=test_password,
                    reason=reason,
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=False,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("SQLite is refused without the test-only opt-in", rejected)

            # 7. Existing internal company is refused.
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password=test_password,
                    reason=reason,
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True
            record("Existing internal company prevents a second bootstrap", rejected)

            # 8. Missing audit table is refused before any creation attempt.
            PlatformAuditLog.__table__.drop(db.engine)
            before_companies = Company.query.count()
            before_users = User.query.count()
            try:
                bootstrap.bootstrap_platform_admin(
                    app,
                    email=approved_email,
                    password=test_password,
                    reason=reason,
                    expected_database=bootstrap.EXPECTED_DATABASE,
                    allow_sqlite_for_tests=True,
                )
                rejected = False
            except bootstrap.BootstrapRefused:
                rejected = True

            unchanged = (
                Company.query.count() == before_companies
                and User.query.count() == before_users
            )
            record(
                "Missing audit table is refused without creating company or user",
                rejected and unchanged,
            )

        # 9. Recreate the audit table in this disposable database, then
        # prove an audit failure rolls back company and administrator creation.
        with app.app_context():
            # Reset only the verified disposable SQLite test database so
            # the rollback test starts without the successful test's records.
            db.drop_all()
            db.create_all()

            import app.platform_audit as audit_module

            original_recorder = audit_module.record_platform_audit

            def fail_audit(**kwargs):
                raise RuntimeError("Deliberate test-only audit failure.")

            audit_module.record_platform_audit = fail_audit
            try:
                try:
                    bootstrap.bootstrap_platform_admin(
                        app,
                        email=bootstrap.EXPECTED_EMAIL,
                        password=test_password,
                        reason=reason,
                        expected_database=bootstrap.EXPECTED_DATABASE,
                        allow_sqlite_for_tests=True,
                    )
                    rolled_back = False
                except RuntimeError as exc:
                    rolled_back = (
                        str(exc) == "Deliberate test-only audit failure."
                    )
            finally:
                audit_module.record_platform_audit = original_recorder

            rollback_ok = (
                rolled_back
                and Company.query.filter_by(
                    name=bootstrap.INTERNAL_COMPANY_NAME
                ).count() == 0
                and User.query.filter_by(
                    email=bootstrap.EXPECTED_EMAIL
                ).count() == 0
                and PlatformAuditLog.query.count() == 0
            )
            record(
                "Audit failure rolls back both company and administrator",
                rollback_ok,
            )

except Exception as exc:
    record("Test execution completed without unexpected exception", False, repr(exc))

finally:
    for key, old_value in OLD_ENV.items():
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print()
print(f"RESULT: {passed} passed, {failed} failed, {len(results)} total")

if failed:
    raise SystemExit(1)
