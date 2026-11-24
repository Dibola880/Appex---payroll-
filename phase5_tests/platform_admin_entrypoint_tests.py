"""
Appex Payroll — Platform Super Admin entry-point regression tests.

TEST-ONLY:
- Uses a disposable SQLite database.
- Disables application startup schema updates.
- Creates test tables only in the temporary SQLite database.
- Does not run migrations or touch Preview/production databases.
"""

import importlib
import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlparse

from werkzeug.security import generate_password_hash

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_platform_admin_tests_")
DB_PATH = os.path.join(TEMP_DIR.name, "platform_admin_tests.db")

ENV_KEYS = (
    "DATABASE_URL",
    "SECRET_KEY",
    "APP_ENV",
    "APPEX_SKIP_STARTUP_SCHEMA_UPDATES",
    "APPEX_ALLOW_STARTUP_SCHEMA_UPDATES",
)
OLD_ENV = {key: os.environ.get(key) for key in ENV_KEYS}

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "platform-admin-tests-only"
os.environ["APP_ENV"] = "testing"
os.environ["APPEX_SKIP_STARTUP_SCHEMA_UPDATES"] = "true"
os.environ.pop("APPEX_ALLOW_STARTUP_SCHEMA_UPDATES", None)

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
    from app.models import Company, Employee, User

    db = app_db
    routes_module = importlib.import_module("app.routes")
    app = create_app()

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        # Safety: prove the app is connected only to this test's SQLite file.
        actual_path = os.path.abspath(db.engine.url.database)
        expected_path = os.path.abspath(DB_PATH)

        isolated = (
            db.engine.dialect.name == "sqlite"
            and actual_path == expected_path
        )
        record(
            "Application uses only the disposable SQLite database",
            isolated,
            f"dialect={db.engine.dialect.name}; database={actual_path}",
        )

        if not isolated:
            raise RuntimeError("Safety stop: unexpected database connection.")

        # Create tables only in the disposable test database.
        db.create_all()

        company = Company(name="Platform Admin Test Company")
        db.session.add(company)
        db.session.flush()

        platform_admin = User(
            company_id=company.id,
            name="Test Platform Administrator",
            email="platform.admin@platform-entrypoint.example.test",
            password_hash=generate_password_hash("PlatformPass123!"),
            role="platform_super_admin",
            is_active=True,
        )

        employer = User(
            company_id=company.id,
            name="Test Employer",
            email="employer@platform-entrypoint.example.test",
            password_hash=generate_password_hash("EmployerPass123!"),
            role="employer",
            is_active=True,
        )

        employee_user = User(
            company_id=company.id,
            name="Test Employee",
            email="employee@platform-entrypoint.example.test",
            password_hash=generate_password_hash("EmployeePass123!"),
            role="employee",
            is_active=True,
        )

        db.session.add_all([platform_admin, employer, employee_user])
        db.session.flush()

        employee = Employee(
            company_id=company.id,
            user_id=employee_user.id,
            employee_number="PLATFORM-TEST-001",
            first_name="Test",
            last_name="Employee",
            email=employee_user.email,
        )
        db.session.add(employee)
        db.session.commit()

        platform_admin_id = platform_admin.id
        employer_id = employer.id
        employee_user_id = employee_user.id

    client = app.test_client()

    with app.test_request_context():
        expected_login_path = url_for("main.login")
        expected_platform_path = url_for("main.platform_dashboard")
        expected_employer_path = url_for("main.dashboard")
        expected_employee_path = url_for("main.employee_dashboard")

    # 1. Anonymous access must redirect to login.
    anonymous_response = client.get(
        "/platform",
        follow_redirects=False,
    )
    record(
        "Anonymous access to platform dashboard redirects to login",
        anonymous_response.status_code == 302
        and response_path(anonymous_response) == expected_login_path,
        f"HTTP {anonymous_response.status_code}; "
        f"redirect={response_path(anonymous_response)}",
    )

    # 2. Platform Super Admin login must redirect to /platform.
    with client.session_transaction() as session:
        session.clear()
        session["old_session_marker"] = "must-be-cleared"

    platform_login = client.post(
        "/login",
        data={
            "email": "platform.admin@platform-entrypoint.example.test",
            "password": "PlatformPass123!",
        },
        follow_redirects=False,
    )

    with client.session_transaction() as session:
        platform_session_ok = (
            session.get("user_id") == platform_admin_id
            and "old_session_marker" not in session
        )

    record(
        "Platform Super Admin login redirects to platform dashboard",
        platform_login.status_code == 302
        and response_path(platform_login) == expected_platform_path,
        f"HTTP {platform_login.status_code}; "
        f"redirect={response_path(platform_login)}",
    )

    record(
        "Platform Super Admin login establishes a fresh session",
        platform_session_ok,
    )

    # 3. Platform Super Admin must be able to open the dashboard.
    platform_dashboard = client.get(
        "/platform",
        follow_redirects=False,
    )
    record(
        "Platform Super Admin can access platform dashboard",
        platform_dashboard.status_code == 200
        and b"Appex Platform Dashboard" in platform_dashboard.data,
        f"HTTP {platform_dashboard.status_code}",
    )

    # 4. Root dashboard must route platform admins to /platform.
    root_response = client.get("/", follow_redirects=False)
    record(
        "Platform Super Admin root dashboard redirects to /platform",
        root_response.status_code == 302
        and response_path(root_response) == expected_platform_path,
        f"HTTP {root_response.status_code}; "
        f"redirect={response_path(root_response)}",
    )

    # 5. Employer login must retain the existing employer destination.
    employer_login = client.post(
        "/login",
        data={
            "email": "employer@platform-entrypoint.example.test",
            "password": "EmployerPass123!",
        },
        follow_redirects=False,
    )
    record(
        "Employer login retains employer dashboard redirect",
        employer_login.status_code == 302
        and response_path(employer_login) == expected_employer_path,
        f"HTTP {employer_login.status_code}; "
        f"redirect={response_path(employer_login)}",
    )

    employer_forbidden = client.get(
        "/platform",
        follow_redirects=False,
    )
    record(
        "Ordinary employer receives HTTP 403 on platform dashboard",
        employer_forbidden.status_code == 403,
        f"HTTP {employer_forbidden.status_code}",
    )

    # 6. Employee login must retain the existing employee destination.
    employee_login = client.post(
        "/login",
        data={
            "email": "employee@platform-entrypoint.example.test",
            "password": "EmployeePass123!",
        },
        follow_redirects=False,
    )
    record(
        "Employee login retains employee dashboard redirect",
        employee_login.status_code == 302
        and response_path(employee_login) == expected_employee_path,
        f"HTTP {employee_login.status_code}; "
        f"redirect={response_path(employee_login)}",
    )

    employee_forbidden = client.get(
        "/platform",
        follow_redirects=False,
    )
    record(
        "Ordinary employee receives HTTP 403 on platform dashboard",
        employee_forbidden.status_code == 403,
        f"HTTP {employee_forbidden.status_code}",
    )

except Exception as exc:
    print("\n[ERROR] Platform admin tests raised an exception:")
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

    for key, value in OLD_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print("\n=== PLATFORM ADMIN ENTRY-POINT TEST SUMMARY ===")
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Total:  {len(results)}")

if failed or not results:
    raise SystemExit(1)

print("\nPASS: All platform admin entry-point tests passed.")
