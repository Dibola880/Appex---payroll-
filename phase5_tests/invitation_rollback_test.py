import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

fd, DB_PATH = tempfile.mkstemp(
    prefix="appex_invitation_rollback_",
    suffix=".db",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "invitation-rollback-test-only"

try:
    from app import create_app, db
    from app.models import Company, Employee, EmployeeInvitation, User

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            raise RuntimeError("Safety check failed: expected SQLite.")

        company = Company(name="Rollback Test Company")
        db.session.add(company)
        db.session.flush()

        employee = Employee(
            company_id=company.id,
            first_name="Rollback",
            last_name="Employee",
            email="rollback.employee@example.test",
            status="Active",
        )
        db.session.add(employee)
        db.session.flush()

        invitation = EmployeeInvitation(
            employee_id=employee.id,
            token="rollback-test-token",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            used=False,
        )
        db.session.add(invitation)
        db.session.commit()

        employee_id = employee.id
        invitation_id = invitation.id
        company_id = company.id

        client = app.test_client()
        original_commit = db.session.commit
        injected_failure = {"triggered": False}

        def fail_commit_once():
            injected_failure["triggered"] = True
            raise RuntimeError("Injected commit failure for test")

        try:
            db.session.commit = fail_commit_once

            response = client.post(
                "/invite/rollback-test-token",
                data={
                    "name": "Rollback Employee",
                    "email": "rollback.new@example.test",
                    "password": "StrongTestPass123!",
                    "confirm_password": "StrongTestPass123!",
                },
                follow_redirects=False,
            )
        finally:
            db.session.commit = original_commit

        db.session.expire_all()

        persisted_user = User.query.filter_by(
            email="rollback.new@example.test"
        ).first()
        persisted_employee = db.session.get(Employee, employee_id)
        persisted_invitation = db.session.get(
            EmployeeInvitation, invitation_id
        )

        checks = [
            (
                "Commit failure was injected",
                injected_failure["triggered"],
            ),
            (
                "Route redirects safely after database failure",
                response.status_code == 302
                and response.headers.get("Location", "").endswith(
                    "/invite/rollback-test-token"
                ),
            ),
            (
                "No partial user account remains",
                persisted_user is None,
            ),
            (
                "Employee remains unlinked",
                persisted_employee is not None
                and persisted_employee.user_id is None
                and persisted_employee.company_id == company_id,
            ),
            (
                "Invitation remains unused",
                persisted_invitation is not None
                and persisted_invitation.used is False,
            ),
        ]

        print("Database dialect:", db.engine.dialect.name)
        print("\nINVITATION ROLLBACK TEST")
        for name, passed in checks:
            print(f"[{'PASS' if passed else 'FAIL'}] {name}")

        failed = sum(not passed for _, passed in checks)
        print(f"\nPassed: {len(checks) - failed}/{len(checks)}")

        if failed:
            raise SystemExit(1)

        print("RESULT: PASSED — rollback safeguards verified.")

except SystemExit:
    raise
except Exception as exc:
    print("[FATAL] Rollback test failed:", repr(exc))
    raise
finally:
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
