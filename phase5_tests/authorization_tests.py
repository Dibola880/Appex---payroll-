import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Always use a fresh temporary SQLite database.
TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_authorization_")
DB_PATH = os.path.join(TEMP_DIR.name, "authorization_tests.db")

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "authorization-isolated-test-only"

results = []

def record(name, passed, details=""):
    results.append((name, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)

try:
    from app import create_app, db
    from app.models import Company, User
    from app.routes import (
        employer_required,
        company_admin_required,
        platform_super_admin_required,
    )
    from flask import url_for

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        dialect = db.engine.dialect.name
        print("Database dialect:", dialect)
        assert dialect == "sqlite", (
            "Safety check failed: database is not SQLite."
        )
        assert os.path.abspath(db.engine.url.database) == os.path.abspath(DB_PATH), (
            "Safety check failed: database path is not the temporary test database."
        )
        record("Disposable SQLite database verified", True)

        company = Company(name="Authorization Test Company")
        db.session.add(company)
        db.session.flush()

        users = {}

        for role in (
            "employee",
            "employer",
            "admin",
            "company_admin",
            "platform_super_admin",
        ):
            user = User(
                company_id=company.id,
                name=f"Test {role}",
                email=f"{role}@authorization.example.test",
                password_hash="isolated-test-hash",
                role=role,
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()
            users[role] = user.id

        db.session.commit()

        # Test-only routes. These are not added to app/routes.py.
        app.add_url_rule(
            "/__auth_test/employer",
            endpoint="auth_test_employer",
            view_func=employer_required(lambda: ("EMPLOYER OK", 200)),
        )
        app.add_url_rule(
            "/__auth_test/company_admin",
            endpoint="auth_test_company_admin",
            view_func=company_admin_required(lambda: ("COMPANY ADMIN OK", 200)),
        )
        app.add_url_rule(
            "/__auth_test/platform_admin",
            endpoint="auth_test_platform_admin",
            view_func=platform_super_admin_required(
                lambda: ("PLATFORM ADMIN OK", 200)
            ),
        )

        client = app.test_client()

        def login_as(role):
            with client.session_transaction() as session:
                session.clear()
                session["user_id"] = users[role]

        def logout():
            with client.session_transaction() as session:
                session.clear()

        def check_status(name, path, expected, role=None):
            if role is None:
                logout()
            else:
                login_as(role)

            response = client.get(path, follow_redirects=False)
            passed = response.status_code == expected
            record(
                name,
                passed,
                f"expected HTTP {expected}, received HTTP {response.status_code}",
            )
            return response

        # Unauthenticated requests must be redirected to login.
        for path, label in (
            ("/__auth_test/employer", "employer"),
            ("/__auth_test/company_admin", "company admin"),
            ("/__auth_test/platform_admin", "platform admin"),
        ):
            response = check_status(
                f"Unauthenticated {label} access is rejected",
                path,
                302,
            )
            with app.test_request_context():
                expected_login = url_for("main.login")
            actual_location = urlparse(response.location or "").path
            record(
                f"Unauthenticated {label} redirects to login",
                actual_location == expected_login,
                f"expected {expected_login}, received {actual_location}",
            )

        # Existing employer permissions remain intact.
        check_status(
            "Employer retains employer-route access",
            "/__auth_test/employer",
            200,
            "employer",
        )
        check_status(
            "Legacy admin retains employer-route access",
            "/__auth_test/employer",
            200,
            "admin",
        )

        # New company-admin role is deliberately not an employer role.
        check_status(
            "Company admin cannot use employer decorator",
            "/__auth_test/employer",
            302,
            "company_admin",
        )
        check_status(
            "Company admin can pass company-admin decorator",
            "/__auth_test/company_admin",
            200,
            "company_admin",
        )

        # Platform privileges are restricted to the exact new role.
        check_status(
            "Platform super admin passes platform decorator",
            "/__auth_test/platform_admin",
            200,
            "platform_super_admin",
        )

        for role in ("employee", "employer", "admin", "company_admin"):
            check_status(
                f"{role} cannot pass platform-admin decorator",
                "/__auth_test/platform_admin",
                403,
                role,
            )

        # Company-admin decorator must reject every other role.
        for role in ("employee", "employer", "admin", "platform_super_admin"):
            check_status(
                f"{role} cannot pass company-admin decorator",
                "/__auth_test/company_admin",
                403,
                role,
            )

        # Employee access to employer routes remains denied.
        check_status(
            "Employee cannot pass employer decorator",
            "/__auth_test/employer",
            302,
            "employee",
        )

        # New administrator roles must not fall through to employer dashboard.
        for role in ("company_admin", "platform_super_admin"):
            check_status(
                f"{role} is denied employer dashboard",
                "/",
                403,
                role,
            )

        # Employee dashboard redirection remains unchanged.
        response = check_status(
            "Employee is redirected from home to employee dashboard",
            "/",
            302,
            "employee",
        )
        with app.test_request_context():
            expected_employee = url_for("main.employee_dashboard")
        actual_employee = urlparse(response.location or "").path
        record(
            "Employee home redirect destination is preserved",
            actual_employee == expected_employee,
            f"expected {expected_employee}, received {actual_employee}",
        )

except Exception as exc:
    print("\n[ERROR] Authorization test execution raised an exception:")
    print(repr(exc))
    traceback.print_exc()
    results.append(("Test execution completed without exception", False))

finally:
    try:
        if "db" in globals():
            db.session.remove()
            db.engine.dispose()
    except Exception:
        pass

    print("\n=== AUTHORIZATION TEST SUMMARY ===")
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(results)}")

    TEMP_DIR.cleanup()

    if failed:
        raise SystemExit(1)

    if not results:
        raise SystemExit(1)

    print("\nPASS: All authorization tests passed.")
