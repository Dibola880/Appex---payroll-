import os
import sys
import tempfile
import traceback
from unittest.mock import patch
from pathlib import Path
from datetime import date

# Make the project root discoverable when this script is run
# from the phase5_tests directory or another working directory.
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Always use a fresh, isolated SQLite database.
fd, DB_PATH = tempfile.mkstemp(
    prefix="appex_phase5_test_",
    suffix=".db",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "phase5-isolated-test-only"

app = None
db = None
results = []


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
        PayrollInput,
        Payslip,
        LoanApplication,
        LoanRepayment,
    )

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        # Correct application-context handling.
        print("Database dialect:", db.engine.dialect.name)
        assert db.engine.dialect.name == "sqlite", (
            "Safety check failed: database is not SQLite."
        )

        def make(Model, **values):
            columns = {c.name for c in Model.__table__.columns}
            unexpected = sorted(set(values) - columns)

            if unexpected:
                raise ValueError(
                    f"Unexpected fields for {Model.__name__}: "
                    f"{unexpected}"
                )

            obj = Model(**values)
            db.session.add(obj)
            db.session.flush()
            return obj

        company_a = make(Company, name="Phase 5 Test Company A")
        company_b = make(Company, name="Phase 5 Test Company B")

        employer_a = make(
            User,
            company_id=company_a.id,
            name="Test Employer A",
            email="phase5-employer-a@example.test",
            password_hash="isolated-test-hash",
            role="employer",
            is_active=True,
        )

        employee_normal = make(
            Employee,
            company_id=company_a.id,
            first_name="Normal",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        employee_loan = make(
            Employee,
            company_id=company_a.id,
            first_name="Loan",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        employee_duplicate = make(
            Employee,
            company_id=company_a.id,
            first_name="Duplicate",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        employee_rollback = make(
            Employee,
            company_id=company_a.id,
            first_name="Rollback",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        employee_foreign = make(
            Employee,
            company_id=company_b.id,
            first_name="Foreign",
            last_name="Employee",
            monthly_salary=10000,
            status="Active",
        )

        def new_run(company, period):
            return make(
                PayrollRun,
                company_id=company.id,
                pay_period=period,
                pay_date=date(2026, 10, 30),
                status="Approved",
            )

        def new_input(run, employee):
            return make(
                PayrollInput,
                payroll_run_id=run.id,
                employee_id=employee.id,
                basic_salary=10000,
                overtime=0,
                bonus=0,
                commission=0,
                other_earnings=0,
                other_deductions=0,
                loan_repayment=0,
            )

        run_normal = new_run(company_a, "Normal Test")
        new_input(run_normal, employee_normal)

        run_loan = new_run(company_a, "Loan Test")
        new_input(run_loan, employee_loan)

        loan = make(
            LoanApplication,
            employee_id=employee_loan.id,
            reference="PHASE5-TEST-LOAN-001",
            requested_amount=1000,
            approved_amount=1000,
            repayment_term="2 months",
            status="Disbursed",
            principal_amount=1000,
            interest_amount=200,
            service_fee_amount=0,
            total_repayable=1200,
            scheduled_installment=600,
            total_paid=200,
            outstanding_balance=1000,
            number_of_payments=2,
        )

        run_duplicate = new_run(company_a, "Duplicate Input Test")
        new_input(run_duplicate, employee_duplicate)
        new_input(run_duplicate, employee_duplicate)

        run_rollback = new_run(company_a, "Rollback Test")
        new_input(run_rollback, employee_rollback)

        rollback_loan = make(
            LoanApplication,
            employee_id=employee_rollback.id,
            reference="PHASE5-TEST-LOAN-002",
            requested_amount=1000,
            approved_amount=1000,
            repayment_term="2 months",
            status="Disbursed",
            principal_amount=1000,
            interest_amount=200,
            service_fee_amount=0,
            total_repayable=1200,
            scheduled_installment=600,
            total_paid=200,
            outstanding_balance=1000,
            number_of_payments=2,
        )

        run_foreign = new_run(company_b, "Company Isolation Test")
        new_input(run_foreign, employee_foreign)

        run_employee_mismatch = new_run(
            company_a,
            "Cross-Company Employee Regression Test",
        )
        new_input(run_employee_mismatch, employee_foreign)

        db.session.commit()

        # Save IDs for use outside this context.
        employer_id = employer_a.id
        normal_id = run_normal.id
        loan_run_id = run_loan.id
        loan_id = loan.id
        loan_employee_id = employee_loan.id
        duplicate_id = run_duplicate.id
        duplicate_employee_id = employee_duplicate.id
        rollback_id = run_rollback.id
        rollback_loan_id = rollback_loan.id
        foreign_id = run_foreign.id
        employee_mismatch_id = run_employee_mismatch.id

    client = app.test_client()

    def login(user_id):
        with client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id

    def complete(run_id):
        login(employer_id)
        return client.post(
            f"/payroll/{run_id}/complete",
            follow_redirects=False,
        )

    print("\nTEST 1: Normal payroll completion")
    response = complete(normal_id)
    with app.app_context():
        run = db.session.get(PayrollRun, normal_id)
        count = Payslip.query.filter_by(
            payroll_run_id=normal_id
        ).count()
        record(
            "Normal payroll completes with one payslip",
            response.status_code in (200, 302)
            and run.status == "Completed"
            and count == 1,
            f"HTTP={response.status_code}; status={run.status}; "
            f"payslips={count}",
        )

    print("\nTEST 2: Repeat completion")
    response = complete(normal_id)
    with app.app_context():
        count = Payslip.query.filter_by(
            payroll_run_id=normal_id
        ).count()
        record(
            "Repeat completion does not duplicate payslips",
            response.status_code in (200, 302) and count == 1,
            f"HTTP={response.status_code}; payslips={count}",
        )

    print("\nTEST 3: Loan repayment ledger")
    response = complete(loan_run_id)
    with app.app_context():
        run = db.session.get(PayrollRun, loan_run_id)
        loan_row = db.session.get(LoanApplication, loan_id)
        slips = Payslip.query.filter_by(
            payroll_run_id=loan_run_id,
            employee_id=loan_employee_id,
        ).all()
        entries = LoanRepayment.query.filter_by(
            loan_application_id=loan_id,
            payroll_run_id=loan_run_id,
        ).all()

        record(
            "Loan payroll completes with one payslip and ledger entry",
            response.status_code in (200, 302)
            and run.status == "Completed"
            and len(slips) == 1
            and len(entries) == 1,
            f"HTTP={response.status_code}; payslips={len(slips)}; "
            f"ledger={len(entries)}",
        )

        if len(entries) == 1 and len(slips) == 1:
            entry = entries[0]
            slip = slips[0]
            record(
                "Repayment amount is R600 in ledger and payslip",
                round(float(entry.amount or 0), 2) == 600
                and round(float(slip.loan_repayment or 0), 2) == 600,
                f"ledger={entry.amount}; payslip={slip.loan_repayment}",
            )
            record(
                "Loan balance changes from R1,000 to R400",
                round(float(entry.balance_before or 0), 2) == 1000
                and round(float(entry.balance_after or 0), 2) == 400
                and round(float(loan_row.outstanding_balance or 0), 2)
                == 400
                and round(float(loan_row.total_paid or 0), 2) == 800,
                f"ledger before={entry.balance_before}; "
                f"ledger after={entry.balance_after}; "
                f"outstanding={loan_row.outstanding_balance}; "
                f"total_paid={loan_row.total_paid}",
            )

    print("\nTEST 4: Duplicate payroll inputs")
    response = complete(duplicate_id)
    with app.app_context():
        run = db.session.get(PayrollRun, duplicate_id)

        count = Payslip.query.filter_by(
            payroll_run_id=duplicate_id,
        ).count()

        ledger_count = LoanRepayment.query.filter_by(
            payroll_run_id=duplicate_id,
        ).count()

        record(
            "Duplicate inputs create no payslips",
            count == 0,
            f"HTTP={response.status_code}; payslips={count}",
        )

        record(
            "Duplicate inputs leave payroll approved",
            run.status == "Approved",
            f"status={run.status}",
        )

        record(
            "Duplicate inputs create no repayment ledger entries",
            ledger_count == 0,
            f"ledger={ledger_count}",
        )

    print("\nTEST 5: Transaction rollback after injected failure")
    import app.routes as routes_module

    original_create_ledger = routes_module.create_loan_repayment_ledger_entry

    def create_ledger_then_fail(*args, **kwargs):
        original_create_ledger(*args, **kwargs)
        raise RuntimeError("Intentional isolated rollback test failure")

    with patch.object(
        routes_module,
        "create_loan_repayment_ledger_entry",
        side_effect=create_ledger_then_fail,
    ):
        response = complete(rollback_id)

    with app.app_context():
        run = db.session.get(PayrollRun, rollback_id)
        loan_row = db.session.get(LoanApplication, rollback_loan_id)
        slip_count = Payslip.query.filter_by(
            payroll_run_id=rollback_id
        ).count()
        ledger_count = LoanRepayment.query.filter_by(
            loan_application_id=rollback_loan_id,
            payroll_run_id=rollback_id,
        ).count()

        record(
            "Injected failure rolls back payslip and ledger writes",
            run.status == "Approved"
            and slip_count == 0
            and ledger_count == 0,
            f"HTTP={response.status_code}; status={run.status}; "
            f"payslips={slip_count}; ledger={ledger_count}",
        )

        record(
            "Injected failure preserves original loan balances",
            round(float(loan_row.total_paid or 0), 2) == 200
            and round(float(loan_row.outstanding_balance or 0), 2) == 1000,
            f"total_paid={loan_row.total_paid}; "
            f"outstanding={loan_row.outstanding_balance}",
        )

    print("\nTEST 6: Company isolation")
    response = complete(foreign_id)
    with app.app_context():
        run = db.session.get(PayrollRun, foreign_id)
        count = Payslip.query.filter_by(
            payroll_run_id=foreign_id
        ).count()
        record(
            "Company A cannot complete Company B payroll",
            response.status_code == 404
            and run.status == "Approved"
            and count == 0,
            f"HTTP={response.status_code}; status={run.status}; "
            f"payslips={count}",
        )

    print("\nTEST 7: Cross-company employee isolation")
    response = complete(employee_mismatch_id)

    with app.app_context():
        run = db.session.get(PayrollRun, employee_mismatch_id)
        slip_count = Payslip.query.filter_by(
            payroll_run_id=employee_mismatch_id
        ).count()
        ledger_count = LoanRepayment.query.filter_by(
            payroll_run_id=employee_mismatch_id
        ).count()

        record(
            "Cross-company employee is rejected without payroll side effects",
            response.status_code in (302, 400, 403, 404)
            and run.status == "Approved"
            and slip_count == 0
            and ledger_count == 0,
            f"HTTP={response.status_code}; status={run.status}; "
            f"payslips={slip_count}; ledger={ledger_count}",
        )

except Exception as exc:
    record(
        "Test setup/execution completed without an uncaught exception",
        False,
        f"{type(exc).__name__}: {exc}",
    )
    traceback.print_exc()

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
    print("TEST SUMMARY")
    print("=" * 55)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(results)}")
    if failed:
        print("Review the FAIL lines above before changing application code.")
    print("Isolated test run finished.")
    if failed:
        sys.exit(1)
