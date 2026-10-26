import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

fd, DB_PATH = tempfile.mkstemp(
    prefix="appex_invitation_test_",
    suffix=".db",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "invitation-test-only-secret"

results = []


def check(name, passed, details=""):
    results.append((name, bool(passed)))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


try:
    from app import create_app, db
    from app.models import Company, User, Employee, EmployeeInvitation
    from werkzeug.security import check_password_hash

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            raise RuntimeError("Safety check failed: database is not SQLite.")

        print("Database dialect:", db.engine.dialect.name)

        company = Company(name="Invitation Test Company")
        db.session.add(company)
        db.session.flush()

        employee = Employee(
            company_id=company.id,
            first_name="Taylor",
            last_name="Employee",
            email="taylor.employee@example.test",
            status="Active",
        )
        db.session.add(employee)
        db.session.flush()

        def new_invitation(emp, token, hours=48, used=False):
            invitation = EmployeeInvitation(
                employee_id=emp.id,
                token=token,
                expires_at=datetime.utcnow() + timedelta(hours=hours),
                used=used,
            )
            db.session.add(invitation)
            db.session.commit()
            return invitation

        valid_invitation = new_invitation(employee, "valid-test-token")

        client = app.test_client()

        print("\nTEST 1: Invitation form")
        response = client.get("/invite/valid-test-token")
        check(
            "Valid invitation displays account setup form",
            response.status_code == 200
            and b'name="name"' in response.data
            and b'name="email"' in response.data
            and b'name="password"' in response.data
            and b'name="confirm_password"' in response.data,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 2: Successful account creation")
        response = client.post(
            "/invite/valid-test-token",
            data={
                "name": "Taylor Newname Employee",
                "email": "TAYLOR.NEW@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
            follow_redirects=False,
        )

        created_user = User.query.filter_by(
            email="taylor.new@example.test"
        ).first()
        db.session.refresh(employee)
        db.session.refresh(valid_invitation)

        check(
            "Valid invitation creates an employee user",
            response.status_code == 302
            and created_user is not None
            and created_user.role == "employee"
            and created_user.is_active,
            f"HTTP={response.status_code}; user_created={created_user is not None}",
        )

        check(
            "User and employee are linked to the correct company and record",
            created_user is not None
            and employee.user_id == created_user.id
            and employee.company_id == company.id
            and created_user.company_id == company.id
            and employee.first_name == "Taylor"
            and employee.last_name == "Newname Employee"
            and employee.email == "taylor.new@example.test",
            f"employee_user_id={employee.user_id}; company_id={company.id}",
        )

        check(
            "Password is hashed and session is established",
            created_user is not None
            and check_password_hash(
                created_user.password_hash,
                "StrongTestPass123!",
            )
            and client.get_cookie("session") is not None,
        )

        check(
            "Successful invitation is marked used",
            valid_invitation.used is True,
        )

        print("\nTEST 3: Employee login")
        client.get("/logout")
        response = client.post(
            "/login",
            data={
                "email": "taylor.new@example.test",
                "password": "StrongTestPass123!",
            },
            follow_redirects=False,
        )
        check(
            "New employee can log in",
            response.status_code == 302
            and response.headers.get("Location", "").endswith("/employee"),
            f"HTTP={response.status_code}; location={response.headers.get('Location')}",
        )

        print("\nTEST 4: Password confirmation mismatch")
        mismatch_employee = Employee(
            company_id=company.id,
            first_name="Mismatch",
            last_name="Employee",
            status="Active",
        )
        db.session.add(mismatch_employee)
        db.session.flush()
        new_invitation(mismatch_employee, "mismatch-test-token")

        before_users = User.query.count()
        response = client.post(
            "/invite/mismatch-test-token",
            data={
                "name": "Mismatch Employee",
                "email": "mismatch@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "DifferentPass123!",
            },
        )
        db.session.expire_all()

        check(
            "Mismatched passwords do not create an account",
            response.status_code == 302
            and User.query.count() == before_users
            and mismatch_employee.user_id is None,
            f"HTTP={response.status_code}; users_before={before_users}; users_after={User.query.count()}",
        )

        print("\nTEST 5: Duplicate email")
        duplicate_employee = Employee(
            company_id=company.id,
            first_name="Duplicate",
            last_name="Employee",
            status="Active",
        )
        db.session.add(duplicate_employee)
        db.session.flush()
        duplicate_invitation = new_invitation(
            duplicate_employee,
            "duplicate-email-test-token",
        )

        before_users = User.query.count()
        response = client.post(
            "/invite/duplicate-email-test-token",
            data={
                "name": "Duplicate Employee",
                "email": "taylor.new@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )
        db.session.expire_all()

        check(
            "Existing email is rejected without creating a user",
            response.status_code == 302
            and User.query.count() == before_users
            and duplicate_employee.user_id is None
            and duplicate_invitation.used is False,
            f"HTTP={response.status_code}; users_before={before_users}; users_after={User.query.count()}",
        )

        print("\nTEST 6: Expired invitation")
        expired_employee = Employee(
            company_id=company.id,
            first_name="Expired",
            last_name="Employee",
            status="Active",
        )
        db.session.add(expired_employee)
        db.session.flush()
        new_invitation(
            expired_employee,
            "expired-test-token",
            hours=-1,
        )

        before_users = User.query.count()
        response = client.post(
            "/invite/expired-test-token",
            data={
                "name": "Expired Employee",
                "email": "expired@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )

        check(
            "Expired invitation cannot create an account",
            response.status_code == 302
            and User.query.count() == before_users
            and expired_employee.user_id is None,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 7: Previously used invitation")
        used_employee = Employee(
            company_id=company.id,
            first_name="Used",
            last_name="Employee",
            status="Active",
        )
        db.session.add(used_employee)
        db.session.flush()
        new_invitation(
            used_employee,
            "used-test-token",
            used=True,
        )

        before_users = User.query.count()
        response = client.post(
            "/invite/used-test-token",
            data={
                "name": "Used Employee",
                "email": "used@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )

        check(
            "Used invitation cannot create an account",
            response.status_code == 302
            and User.query.count() == before_users
            and used_employee.user_id is None,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 8: Invalid invitation")
        before_users = User.query.count()
        response = client.post(
            "/invite/invalid-test-token",
            data={
                "name": "Invalid Employee",
                "email": "invalid@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )

        check(
            "Unknown invitation token is rejected",
            response.status_code == 302
            and User.query.count() == before_users,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 9: Short password")
        short_employee = Employee(
            company_id=company.id,
            first_name="Short",
            last_name="Password",
            status="Active",
        )
        db.session.add(short_employee)
        db.session.flush()
        new_invitation(short_employee, "short-password-test-token")

        before_users = User.query.count()
        response = client.post(
            "/invite/short-password-test-token",
            data={
                "name": "Short Password",
                "email": "short@example.test",
                "password": "short",
                "confirm_password": "short",
            },
        )

        check(
            "Password shorter than 8 characters is rejected",
            response.status_code == 302
            and User.query.count() == before_users
            and short_employee.user_id is None,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 10: Missing full name")
        missing_name_employee = Employee(
            company_id=company.id,
            first_name="Missing",
            last_name="Name",
            status="Active",
        )
        db.session.add(missing_name_employee)
        db.session.flush()
        new_invitation(missing_name_employee, "missing-name-test-token")

        before_users = User.query.count()
        response = client.post(
            "/invite/missing-name-test-token",
            data={
                "name": "   ",
                "email": "missingname@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )

        check(
            "Missing full name is rejected",
            response.status_code == 302
            and User.query.count() == before_users
            and missing_name_employee.user_id is None,
            f"HTTP={response.status_code}",
        )

        print("\nTEST 11: Employee already linked to an account")
        linked_employee = Employee(
            company_id=company.id,
            first_name="Already",
            last_name="Linked",
            status="Active",
        )
        db.session.add(linked_employee)
        db.session.flush()

        linked_user = User(
            company_id=company.id,
            name="Already Linked",
            email="already.linked@example.test",
            password_hash="not-used-in-this-test",
            role="employee",
            is_active=True,
        )
        db.session.add(linked_user)
        db.session.flush()
        linked_employee.user_id = linked_user.id
        db.session.flush()
        new_invitation(linked_employee, "already-linked-test-token")

        before_users = User.query.count()
        response = client.post(
            "/invite/already-linked-test-token",
            data={
                "name": "Already Linked",
                "email": "already.linked.new@example.test",
                "password": "StrongTestPass123!",
                "confirm_password": "StrongTestPass123!",
            },
        )

        check(
            "Invitation cannot create a second account for a linked employee",
            response.status_code == 302
            and User.query.count() == before_users
            and linked_employee.user_id == linked_user.id,
            f"HTTP={response.status_code}",
        )

except Exception as exc:
    print("\n[FATAL] Invitation test execution failed:", repr(exc))
    import traceback
    traceback.print_exc()
    results.append(("Test script completed without an exception", False))

finally:
    print("\n" + "=" * 55)
    print("INVITATION TEST SUMMARY")
    print("=" * 55)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(results)}")

    if failed:
        print("RESULT: FAILED — review the failing checks above.")
    else:
        print("RESULT: PASSED — all invitation checks passed.")

    try:
        if "db" in globals():
            db.session.remove()
    except Exception:
        pass

    try:
        if os.path.exists(DB_PATH):
            os.unlink(DB_PATH)
    except Exception:
        pass

    sys.exit(1 if failed else 0)
