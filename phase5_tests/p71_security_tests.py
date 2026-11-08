import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from urllib.parse import urlparse

# Force an isolated development/test environment before importing the app.
TEMP_DIR = tempfile.TemporaryDirectory(prefix="appex_p71_security_")
DB_PATH = Path(TEMP_DIR.name) / "p71_security_tests.db"

os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "p71-security-test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Company, User, Employee, EmployeeInvitation


results = []


def record(name, passed, detail=""):
    results.append((name, bool(passed), detail))
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")


def csrf_token(response):
    html = response.get_data(as_text=True)
    match = re.search(
        r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if not match:
        raise AssertionError("CSRF token input was not found in the response.")
    return match.group(1)


app = create_app()
app.config.update(
    TESTING=True,
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_CHECK_DEFAULT=True,
)

try:
    with app.app_context():
        # Safety: this suite must never use the application's normal database.
        database_name = db.engine.url.database
        database_dialect = db.engine.dialect.name
        database_path = os.path.abspath(database_name) if database_name else None

        if database_dialect != "sqlite":
            raise RuntimeError("Safety stop: test database is not SQLite.")
        if not database_name or database_path != str(DB_PATH):
            raise RuntimeError(
                "Safety stop: database path does not match the disposable test DB."
            )

        db.create_all()

        company = Company(name="P7.1 Security Test Company")
        db.session.add(company)
        db.session.flush()

        employer = User(
            company_id=company.id,
            name="Security Test Employer",
            email="p71-employer@example.test",
            password_hash=generate_password_hash("TestPassword!123"),
            role="employer",
            is_active=True,
        )
        db.session.add(employer)
        db.session.flush()

        employee = Employee(
            company_id=company.id,
            first_name="Security",
            last_name="Test Employee",
            email="p71-employee@example.test",
            status="Active",
        )
        db.session.add(employee)
        db.session.commit()

        employer_id = employer.id
        employee_id = employee.id

    client = app.test_client()

    print("\n===== DATABASE SAFETY =====")
    record(
        "Disposable SQLite database selected",
        database_dialect == "sqlite"
        and database_path == str(DB_PATH),
        str(DB_PATH),
    )

    print("\n===== METHOD RESTRICTIONS =====")
    response = client.get("/logout")
    record("GET /logout is rejected", response.status_code == 405,
           f"HTTP {response.status_code}")

    response = client.get(f"/employees/{employee_id}/invite")
    record("GET canonical invitation route is rejected",
           response.status_code == 405, f"HTTP {response.status_code}")

    response = client.get(f"/employees/{employee_id}/create-invitation")
    record("GET compatibility invitation route is rejected",
           response.status_code == 405, f"HTTP {response.status_code}")

    print("\n===== LOGIN AND CSRF PROTECTION =====")
    response = client.get("/login")
    record("Login page loads", response.status_code == 200,
           f"HTTP {response.status_code}")
    login_token = csrf_token(response)

    response = client.post(
        "/login",
        data={
            "email": "p71-employer@example.test",
            "password": "TestPassword!123",
        },
    )
    record("Login without CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    response = client.post(
        "/login",
        data={
            "email": "p71-employer@example.test",
            "password": "TestPassword!123",
            "csrf_token": "invalid-token",
        },
    )
    record("Login with invalid CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    response = client.post(
        "/login",
        data={
            "email": "p71-employer@example.test",
            "password": "TestPassword!123",
            "csrf_token": login_token,
        },
    )
    record("Employer login with valid CSRF token succeeds",
           response.status_code in (302, 303),
           f"HTTP {response.status_code}")

    print("\n===== INVITATION CSRF PROTECTION =====")
    response = client.get("/employees")
    record("Employer employee page loads", response.status_code == 200,
           f"HTTP {response.status_code}")
    employee_page_token = csrf_token(response)

    with app.app_context():
        before_count = EmployeeInvitation.query.filter_by(
            employee_id=employee_id
        ).count()

    response = client.post(
        f"/employees/{employee_id}/create-invitation"
    )
    record("Invitation POST without CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    with app.app_context():
        after_missing_token_count = EmployeeInvitation.query.filter_by(
            employee_id=employee_id
        ).count()

    record("Rejected invitation creates no invitation",
           after_missing_token_count == before_count,
           f"before={before_count}, after={after_missing_token_count}")

    response = client.post(
        f"/employees/{employee_id}/create-invitation",
        data={"csrf_token": "invalid-token"},
    )
    record("Invitation POST with invalid CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    with app.app_context():
        after_invalid_token_count = EmployeeInvitation.query.filter_by(
            employee_id=employee_id
        ).count()

    record("Invalid-token invitation creates no invitation",
           after_invalid_token_count == before_count,
           f"before={before_count}, after={after_invalid_token_count}")

    response = client.post(
        f"/employees/{employee_id}/create-invitation",
        data={"csrf_token": employee_page_token},
    )
    record("Invitation POST with valid CSRF token succeeds",
           response.status_code in (302, 303),
           f"HTTP {response.status_code}")

    with app.app_context():
        after_valid_token_count = EmployeeInvitation.query.filter_by(
            employee_id=employee_id
        ).count()

    record("Valid invitation creates exactly one invitation",
           after_valid_token_count == before_count + 1,
           f"before={before_count}, after={after_valid_token_count}")

    print("\n===== LOGOUT CSRF PROTECTION =====")
    response = client.get("/employees")
    logout_token = csrf_token(response)

    response = client.post("/logout")
    record("Logout POST without CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    response = client.post(
        "/logout",
        data={"csrf_token": "invalid-token"},
    )
    record("Logout POST with invalid CSRF token is rejected",
           response.status_code == 400, f"HTTP {response.status_code}")

    response = client.post(
        "/logout",
        data={"csrf_token": logout_token},
    )
    record("Logout POST with valid CSRF token succeeds",
           response.status_code in (302, 303),
           f"HTTP {response.status_code}")

    record("Successful logout redirects to login",
           urlparse(response.headers.get("Location", "")).path == "/login",
           response.headers.get("Location", ""))

    with client.session_transaction() as session:
        record("Successful logout clears authenticated session",
               "user_id" not in session)

    print("\n===== INACTIVE SESSION REJECTION =====")
    response = client.get("/login")
    inactive_login_token = csrf_token(response)

    response = client.post(
        "/login",
        data={
            "email": "p71-employer@example.test",
            "password": "TestPassword!123",
            "csrf_token": inactive_login_token,
        },
    )
    record("Employer can log in before deactivation",
           response.status_code in (302, 303),
           f"HTTP {response.status_code}")

    with app.app_context():
        user = db.session.get(User, employer_id)
        user.is_active = False
        db.session.commit()

    response = client.get("/employees")
    record("Inactive authenticated user is denied employee page",
           response.status_code in (302, 303),
           f"HTTP {response.status_code}")

    record("Inactive user is redirected to login",
           urlparse(response.headers.get("Location", "")).path == "/login",
           response.headers.get("Location", ""))

    with client.session_transaction() as session:
        record("Inactive user's session is cleared",
               "user_id" not in session)

except Exception as exc:
    record("Unexpected test-suite exception", False,
           f"{type(exc).__name__}: {exc}")
    raise

finally:
    try:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    except Exception:
        pass
    TEMP_DIR.cleanup()

print("\n===== P7.1 SECURITY TEST SUMMARY =====")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print(f"Total:  {len(results)}")

if failed:
    print("\nFAILED TESTS:")
    for name, ok, detail in results:
        if not ok:
            print(f"- {name}: {detail}")
    sys.exit(1)

print("\nP7.1 SECURITY TEST SUITE: PASS")
