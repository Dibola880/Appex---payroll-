import os
import sys
import tempfile
import traceback
from pathlib import Path
from datetime import date

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

fd, DB_PATH = tempfile.mkstemp(
    prefix="appex_company_admin_test_",
    suffix=".db",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "company-admin-isolation-test-only"

results = []
app = None
db = None


def record(name, passed, details=""):
    results.append((name, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


try:
    from app import create_app, db
    from app.models import (
        Company,
        User,
        Employee,
        PayrollRun,
        Payslip,
        LoanApplication,
    )

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        print("Database dialect:", db.engine.dialect.name)
        assert db.engine.dialect.name == "sqlite", (
            "Safety check failed: database is not SQLite."
        )

        def make(Model, **values):
            columns = {c.name for c in Model.__table__.columns}
            obj = Model(
                **{
                    key: value
                    for key, value in values.items()
                    if key in columns
                }
            )
            db.session.add(obj)
            db.session.flush()
            return obj

        company_a = make(
            Company,
            name="Company Admin Test A",
        )
        company_b = make(
            Company,
            name="Company Admin Test B",
        )

        company_admin = make(
            User,
            company_id=company_a.id,
            name="Company A Administrator",
            email="company-admin-a@example.test",
            password_hash="isolated-test-hash",
            role="company_admin",
            is_active=True,
        )

        employee_a = make(
            Employee,
            company_id=company_a.id,
            first_name="Company A",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        employee_b = make(
            Employee,
            company_id=company_b.id,
            first_name="Company B",
            last_name="Foreign Employee",
            monthly_salary=10000,
            status="Active",
        )

        payroll_a = make(
            PayrollRun,
            company_id=company_a.id,
            pay_period="COMPANY-A-ONLY-PAYROLL",
            pay_date=date(2026, 10, 30),
            status="Approved",
        )

        payroll_b = make(
            PayrollRun,
            company_id=company_b.id,
            pay_period="COMPANY-B-PRIVATE-PAYROLL",
            pay_date=date(2026, 10, 30),
            status="Approved",
        )

        payslip_a = make(
            Payslip,
            employee_id=employee_a.id,
            payroll_run_id=payroll_a.id,
            pay_period="COMPANY-A-ONLY-PAYSLIP",
            pay_date=date(2026, 10, 30),
            basic_salary=10000,
            gross_pay=10000,
            net_pay=10000,
        )

        payslip_b = make(
            Payslip,
            employee_id=employee_b.id,
            payroll_run_id=payroll_b.id,
            pay_period="COMPANY-B-PRIVATE-PAYSLIP",
            pay_date=date(2026, 10, 30),
            basic_salary=10000,
            gross_pay=10000,
            net_pay=10000,
        )

        foreign_loan = make(
            LoanApplication,
            employee_id=employee_b.id,
            reference="COMPANY-B-PRIVATE-LOAN",
            requested_amount=500,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )

        ids = {
            "admin": company_admin.id,
            "payroll_a": payroll_a.id,
            "payroll_b": payroll_b.id,
            "payslip_a": payslip_a.id,
            "payslip_b": payslip_b.id,
            "foreign_loan": foreign_loan.id,
        }

        db.session.commit()

    client = app.test_client()

    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = ids["admin"]

    print("\nTEST 1: Company employee visibility")
    response = client.get("/employees")
    body = response.get_data(as_text=True)

    record(
        "Company administrator can open employee list",
        response.status_code == 200,
        f"HTTP={response.status_code}",
    )

    record(
        "Company A employee is visible",
        "Company A" in body and "Employee" in body,
    )

    record(
        "Company B employee is not visible",
        "Foreign Employee" not in body,
    )

    print("\nTEST 2: Payroll history and detail")
    response = client.get("/payroll/history")
    body = response.get_data(as_text=True)

    record(
        "Company administrator can open payroll history",
        response.status_code == 200,
        f"HTTP={response.status_code}",
    )

    record(
        "Company A payroll appears in history",
        "COMPANY-A-ONLY-PAYROLL" in body,
    )

    record(
        "Company B payroll is excluded from history",
        "COMPANY-B-PRIVATE-PAYROLL" not in body,
    )

    response = client.get(
        f"/payroll/{ids['payroll_a']}"
    )
    record(
        "Company administrator can open own payroll detail",
        response.status_code == 200,
        f"HTTP={response.status_code}",
    )

    response = client.get(
        f"/payroll/{ids['payroll_b']}"
    )
    record(
        "Company B payroll detail is denied",
        response.status_code == 404,
        f"HTTP={response.status_code}",
    )

    print("\nTEST 3: Payslip access")
    response = client.get(
        f"/payroll/payslip/{ids['payslip_a']}"
    )
    record(
        "Company administrator can view own company payslip",
        response.status_code == 200,
        f"HTTP={response.status_code}",
    )

    response = client.get(
        f"/payroll/payslip/{ids['payslip_b']}"
    )
    body = response.get_data(as_text=True)

    record(
        "Company B payslip viewing is denied",
        response.status_code in (301, 302, 303),
        f"HTTP={response.status_code}; redirect={response.headers.get('Location')}",
    )

    record(
        "Foreign payslip content is not returned",
        "COMPANY-B-PRIVATE-PAYSLIP" not in body,
    )

    print("\nTEST 4: Payslip PDF access")
    response = client.get(
        f"/payroll/payslip/{ids['payslip_a']}/pdf"
    )
    record(
        "Company administrator can download own company PDF",
        response.status_code == 200
        and response.mimetype == "application/pdf",
        f"HTTP={response.status_code}; type={response.mimetype}",
    )

    response = client.get(
        f"/payroll/payslip/{ids['payslip_b']}/pdf"
    )
    record(
        "Company B payslip PDF download is denied",
        response.status_code in (301, 302, 303),
        f"HTTP={response.status_code}; redirect={response.headers.get('Location')}",
    )

    print("\nTEST 5: Cross-company loan approval")
    response = client.post(
        f"/loans/{ids['foreign_loan']}/approve",
        data={"approved_amount": "500"},
    )

    with app.app_context():
        row = db.session.get(
            LoanApplication,
            ids["foreign_loan"],
        )

        record(
            "Company B loan approval is denied without mutation",
            response.status_code == 404
            and row.status == "Submitted"
            and row.approved_amount is None
            and row.reviewed_by is None,
            f"HTTP={response.status_code}; status={row.status}; "
            f"approved={row.approved_amount}; reviewer={row.reviewed_by}",
        )

except Exception as exc:
    print(
        "\n[TEST SCRIPT ERROR]",
        type(exc).__name__ + ":",
        exc,
    )
    traceback.print_exc()
    results.append(
        ("Test script completed without unexpected exceptions", False)
    )

finally:
    if app is not None and db is not None:
        try:
            with app.app_context():
                db.session.rollback()
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass

    if DB_PATH and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError as exc:
            print("Temporary database cleanup warning:", exc)

    print("\n" + "=" * 55)
    print("COMPANY ADMIN ISOLATION TEST SUMMARY")
    print("=" * 55)

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)

    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(results)}")

    if failed:
        print("Review FAIL lines before changing application code.")
    else:
        print("RESULT: PASSED — all tests completed without script errors.")

    print("Isolated test run finished.")

if failed:
    sys.exit(1)

sys.exit(0)
