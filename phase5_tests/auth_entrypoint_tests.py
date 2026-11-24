"""
Appex Payroll Phase 5 — Authentication and entry-point regression tests.

TEST-ONLY:
- Uses a disposable SQLite database.
- Does not edit production code or templates.
- Does not run migrations or install packages.
- Does not touch the repository's existing database or backup files.

Run from the repository root:
    .venv/bin/python phase5_tests/auth_entrypoint_tests.py
"""

import importlib
import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash


PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_auth_entrypoints_")
DB_PATH = os.path.join(TEMP_DIR.name, "auth_entrypoint_tests.db")

OLD_DATABASE_URL = os.environ.get("DATABASE_URL")
OLD_SECRET_KEY = os.environ.get("SECRET_KEY")

# Set these before importing the application.
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "auth-entrypoint-tests-only"

results = []
app = None
db = None


def record(name, passed, details=""):
    results.append((name, bool(passed)))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


def response_path(response):
    return urlparse(response.location or "").path


try:
    from flask import url_for

    from app import create_app, db as app_db
    from app.models import Company, Employee, User, SubscriptionPlan

    db = app_db
    routes_module = importlib.import_module("app.routes")

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        # Safety: prove the app is using only this script's disposable DB.
        actual_db_path = os.path.abspath(db.engine.url.database)
        expected_db_path = os.path.abspath(DB_PATH)
        record(
            "Disposable SQLite database is isolated",
            db.engine.dialect.name == "sqlite"
            and actual_db_path == expected_db_path,
            f"dialect={db.engine.dialect.name}; database={actual_db_path}",
        )
        if db.engine.dialect.name != "sqlite" or actual_db_path != expected_db_path:
            raise RuntimeError(
                "Safety stop: application is not connected to the expected "
                "temporary SQLite database."
            )

        # Seed the centrally managed Free Trial plan in this disposable
        # SQLite database so registration tests exercise the real route.
        free_trial_plan = SubscriptionPlan(
            code="free_trial",
            name="Free Trial",
            description="Test-only Free Trial plan",
            monthly_price=0,
            annual_price=0,
            currency="ZAR",
            billing_intervals=["monthly", "annually"],
            employee_limit=None,
            feature_config={},
            is_active=True,
        )
        db.session.add(free_trial_plan)
        db.session.flush()

        # Fixtures used by the repayment-route and login checks.
        company = Company(name="Auth Entrypoint Test Company")
        db.session.add(company)
        db.session.flush()

        employee_user = User(
            company_id=company.id,
            name="Repayment Test Employee",
            email="repayment.employee@auth-entrypoint.example.test",
            password_hash=generate_password_hash("EmployeePass123!"),
            role="employee",
            is_active=True,
        )
        active_employer = User(
            company_id=company.id,
            name="Login Test Employer",
            email="login.employer@auth-entrypoint.example.test",
            password_hash=generate_password_hash("EmployerPass123!"),
            role="employer",
            is_active=True,
        )
        inactive_employer = User(
            company_id=company.id,
            name="Inactive Test Employer",
            email="inactive.employer@auth-entrypoint.example.test",
            password_hash=generate_password_hash("InactivePass123!"),
            role="employer",
            is_active=False,
        )
        db.session.add_all(
            [employee_user, active_employer, inactive_employer]
        )
        db.session.flush()

        employee = Employee(
            company_id=company.id,
            user_id=employee_user.id,
            employee_number="AUTH-TEST-EMP-001",
            first_name="Repayment",
            last_name="Employee",
            email=employee_user.email,
        )
        db.session.add(employee)
        db.session.commit()

        employee_user_id = employee_user.id
        active_employer_id = active_employer.id
        inactive_employer_id = inactive_employer.id

        app.add_url_rule(
            "/__auth_entrypoint_test/company_admin_missing",
            endpoint="auth_entrypoint_company_admin_missing",
            view_func=routes_module.company_admin_required(
                lambda: ("UNEXPECTED ACCESS", 200)
            ),
            methods=["GET"],
        )

        client = app.test_client()

        # ------------------------------------------------------------
        # 1–2. Employee repayment compatibility URL
        # ------------------------------------------------------------
        anonymous_response = client.get(
            "/employee/repayments",
            follow_redirects=False,
        )
        with app.test_request_context():
            expected_login_path = url_for("main.login")
        record(
            "Anonymous repayment-route request redirects to login",
            anonymous_response.status_code == 302
            and response_path(anonymous_response) == expected_login_path,
            f"HTTP {anonymous_response.status_code}; "
            f"location={response_path(anonymous_response)}",
        )

        with client.session_transaction() as session:
            session.clear()
            session["user_id"] = employee_user_id

        employee_response = client.get(
            "/employee/repayments",
            follow_redirects=False,
        )
        record(
            "Linked employee can access repayment compatibility URL",
            employee_response.status_code == 200
            and b"Repayment History" in employee_response.data,
            f"HTTP {employee_response.status_code}; "
            "response contains repayment-history section"
            if employee_response.status_code == 200
            else employee_response.get_data(as_text=True)[:300],
        )

        # ------------------------------------------------------------
        # 3. Company-admin role without a company association
        # ------------------------------------------------------------

        mock_company_admin_without_company = SimpleNamespace(
            role="company_admin",
            company_id=None,
            company=None,
        )
        with patch.object(
            routes_module,
            "current_user",
            return_value=mock_company_admin_without_company,
        ):
            no_company_response = client.get(
                "/__auth_entrypoint_test/company_admin_missing",
                follow_redirects=False,
            )

        record(
            "Company admin without company association receives HTTP 403",
            no_company_response.status_code == 403,
            f"expected HTTP 403, received HTTP {no_company_response.status_code}",
        )

        # ------------------------------------------------------------
        # 4–8. Registration entry point
        # ------------------------------------------------------------
        registration_page = client.get("/register")
        record(
            "Registration page loads successfully",
            registration_page.status_code == 200
            and b'name="company_name"' in registration_page.data
            and b'name="name"' in registration_page.data
            and b'name="email"' in registration_page.data
            and b'name="password"' in registration_page.data,
            f"HTTP {registration_page.status_code}",
        )

        company_count_before_registration = Company.query.count()
        user_count_before_registration = User.query.count()

        with client.session_transaction() as session:
            session.clear()
            session["pre_registration_marker"] = "must-be-cleared"

        registration_response = client.post(
            "/register",
            data={
                "company_name": "New Registration Test Company",
                "name": "New Test Employer",
                "email": "  New.Employer@Auth-EntryPoint.Example.Test  ",
                "password": "RegistrationPass123!",
                "confirm_password": "RegistrationPass123!",
            },
            follow_redirects=False,
        )

        registered_user = User.query.filter_by(
            email="new.employer@auth-entrypoint.example.test"
        ).first()

        registration_ok = (
            registration_response.status_code == 302
            and registered_user is not None
            and registered_user.role == "employer"
            and registered_user.is_active is True
            and registered_user.company is not None
            and registered_user.company.name == "New Registration Test Company"
            and Company.query.count() == company_count_before_registration + 1
            and User.query.count() == user_count_before_registration + 1
        )
        record(
            "Valid registration creates one active employer and company",
            registration_ok,
            f"HTTP {registration_response.status_code}; "
            f"user_created={registered_user is not None}; "
            f"companies={Company.query.count()}; users={User.query.count()}",
        )

        password_ok = (
            registered_user is not None
            and registered_user.password_hash != "RegistrationPass123!"
            and check_password_hash(
                registered_user.password_hash,
                "RegistrationPass123!",
            )
        )
        record(
            "Registration stores a verifiable password hash",
            password_ok,
        )

        with client.session_transaction() as session:
            registration_session_ok = (
                registered_user is not None
                and session.get("user_id") == registered_user.id
                and "pre_registration_marker" not in session
            )
            registration_session_details = {
                "session_user_id": session.get("user_id"),
                "expected_user_id": (
                    registered_user.id if registered_user else None
                ),
                "old_marker_present": (
                    "pre_registration_marker" in session
                ),
            }
        record(
            "Registration establishes a fresh authenticated session",
            registration_session_ok,
            str(registration_session_details),
        )

        # Duplicate registration must not create another company or user.
        duplicate_company_count = Company.query.count()
        duplicate_user_count = User.query.count()

        duplicate_response = client.post(
            "/register",
            data={
                "company_name": "Must Not Be Created",
                "name": "Duplicate Test User",
                "email": "NEW.EMPLOYER@AUTH-ENTRYPOINT.EXAMPLE.TEST",
                "password": "AnotherPass123!",
                "confirm_password": "AnotherPass123!",
            },
            follow_redirects=False,
        )

        with app.test_request_context():
            expected_duplicate_redirect = url_for("main.login")

        duplicate_ok = (
            duplicate_response.status_code == 302
            and response_path(duplicate_response) == expected_duplicate_redirect
            and Company.query.count() == duplicate_company_count
            and User.query.count() == duplicate_user_count
        )
        record(
            "Duplicate registration is rejected without creating records",
            duplicate_ok,
            f"HTTP {duplicate_response.status_code}; "
            f"redirect={response_path(duplicate_response)}; "
            f"companies={Company.query.count()}; users={User.query.count()}",
        )

        # ------------------------------------------------------------
        # 9–12. Login entry point
        # ------------------------------------------------------------
        with client.session_transaction() as session:
            session.clear()
            session["pre_login_marker"] = "must-be-cleared"

        login_response = client.post(
            "/login",
            data={
                "email": "  LOGIN.EMPLOYER@AUTH-ENTRYPOINT.EXAMPLE.TEST ",
                "password": "EmployerPass123!",
            },
            follow_redirects=False,
        )

        with app.test_request_context():
            expected_dashboard_path = url_for("main.dashboard")

        record(
            "Valid login redirects to the employer dashboard",
            login_response.status_code == 302
            and response_path(login_response) == expected_dashboard_path,
            f"HTTP {login_response.status_code}; "
            f"redirect={response_path(login_response)}",
        )

        with client.session_transaction() as session:
            login_session_ok = (
                session.get("user_id") == active_employer_id
                and "pre_login_marker" not in session
            )
            login_session_details = {
                "session_user_id": session.get("user_id"),
                "expected_user_id": active_employer_id,
                "old_marker_present": "pre_login_marker" in session,
            }
        record(
            "Successful login replaces the previous session",
            login_session_ok,
            str(login_session_details),
        )

        # Inactive account must not establish an authenticated session.
        with client.session_transaction() as session:
            session.clear()

        inactive_response = client.post(
            "/login",
            data={
                "email": "inactive.employer@auth-entrypoint.example.test",
                "password": "InactivePass123!",
            },
            follow_redirects=False,
        )
        with client.session_transaction() as session:
            inactive_session_ok = "user_id" not in session

        with app.test_request_context():
            expected_login_path = url_for("main.login")

        record(
            "Inactive account login is rejected without authentication",
            inactive_response.status_code == 302
            and response_path(inactive_response) == expected_login_path
            and inactive_session_ok,
            f"HTTP {inactive_response.status_code}; "
            f"redirect={response_path(inactive_response)}; "
            f"user_id_in_session={not inactive_session_ok}",
        )

        # Incorrect password must not establish an authenticated session.
        with client.session_transaction() as session:
            session.clear()

        wrong_password_response = client.post(
            "/login",
            data={
                "email": "login.employer@auth-entrypoint.example.test",
                "password": "DefinitelyWrongPassword!",
            },
            follow_redirects=False,
        )
        with client.session_transaction() as session:
            wrong_password_session_ok = "user_id" not in session

        record(
            "Incorrect password is rejected without authentication",
            wrong_password_response.status_code == 302
            and response_path(wrong_password_response) == expected_login_path
            and wrong_password_session_ok,
            f"HTTP {wrong_password_response.status_code}; "
            f"redirect={response_path(wrong_password_response)}; "
            f"user_id_in_session={not wrong_password_session_ok}",
        )

except Exception as exc:
    print("\n[ERROR] Authentication entry-point tests raised an exception:")
    print(repr(exc))
    traceback.print_exc()
    results.append(("Test execution completed without exception", False))

finally:
    try:
        if app is not None and db is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    except Exception:
        pass

    TEMP_DIR.cleanup()

    if OLD_DATABASE_URL is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = OLD_DATABASE_URL

    if OLD_SECRET_KEY is None:
        os.environ.pop("SECRET_KEY", None)
    else:
        os.environ["SECRET_KEY"] = OLD_SECRET_KEY


print("\n=== AUTHENTICATION ENTRY-POINT TEST SUMMARY ===")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Total:  {len(results)}")

if failed or not results:
    raise SystemExit(1)

print("\nPASS: All authentication entry-point tests passed.")
