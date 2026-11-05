import os
import sys
import tempfile
import traceback
from pathlib import Path
from datetime import date
from sqlalchemy.exc import IntegrityError

# Make the project root discoverable when this script is run
# from the phase5_tests directory or another working directory.
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
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
script_error = False


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

    from app.routes import create_loan_repayment_ledger_entry

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
            obj = Model(
                **{key: value for key, value in values.items()
                   if key in columns}
            )
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
                salary=10000,
                monthly_salary=10000,
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
            service_fee=0,
            total_repayable=1200,
            scheduled_installment=600,
            total_paid=200,
            outstanding_balance=1000,
            number_of_payments=2,
        )

        historical_entry = make(
            LoanRepayment,
            loan_application_id=loan.id,
            employee_id=employee_loan.id,
            amount=200,
            balance_before=1200,
            balance_after=1000,
            payment_number=1,
            status="Completed",
            payment_method="Historical Test Payment",
            reference="PHASE5-HISTORICAL-200",
            repayment_date=date(2026, 9, 30),
        )
        run_duplicate = new_run(company_a, "Duplicate Input Test")
        new_input(run_duplicate, employee_duplicate)
        new_input(run_duplicate, employee_duplicate)

        run_rollback = new_run(company_a, "Rollback Test")
        new_input(run_rollback, employee_rollback)
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
            service_fee=0,
            total_repayable=1200,
            scheduled_installment=600,
            total_paid=200,
            outstanding_balance=1000,
            number_of_payments=2,
        )

        run_foreign = new_run(company_b, "Company Isolation Test")
        new_input(run_foreign, employee_foreign)

        db.session.commit()

        # Save IDs for use outside this context.
        employer_id = employer_a.id
        company_a_id = company_a.id
        normal_id = run_normal.id
        loan_run_id = run_loan.id
        loan_id = loan.id
        loan_employee_id = employee_loan.id
        duplicate_id = run_duplicate.id
        duplicate_employee_id = employee_duplicate.id
        rollback_id = run_rollback.id
        rollback_loan_id = rollback_loan.id
        foreign_id = run_foreign.id

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
                "Loan balance reconciles with historical repayment",
                round(float(entry.balance_before or 0), 2) == 1000
                and round(float(entry.balance_after or 0), 2) == 400
                and round(float(loan_row.outstanding_balance or 0), 2) == 400
                and round(float(loan_row.total_paid or 0), 2) == 800,
                f"before={entry.balance_before}; after={entry.balance_after}; "
                f"paid={loan_row.total_paid}; outstanding={loan_row.outstanding_balance}",
            )
            all_entries = LoanRepayment.query.filter_by(
                loan_application_id=loan_id,
                status="Completed",
            ).order_by(LoanRepayment.payment_number.asc()).all()
            amounts = [round(float(item.amount or 0), 2) for item in all_entries]
            record(
                "Historical and payroll repayments reconcile to R800",
                len(all_entries) == 2 and sum(amounts) == 800,
                f"count={len(all_entries)}; amounts={amounts}; sum={sum(amounts)}",
            )
            record(
                "Repayment numbers are sequential",
                len(all_entries) == 2
                and [item.payment_number for item in all_entries] == [1, 2],
                f"payment_numbers={[item.payment_number for item in all_entries]}",
            )
            record(
                "Repayment balance chain is consistent",
                len(all_entries) == 2
                and round(float(all_entries[0].balance_before or 0), 2) == 1200
                and round(float(all_entries[0].balance_after or 0), 2) == 1000
                and round(float(all_entries[1].balance_before or 0), 2) == 1000
                and round(float(all_entries[1].balance_after or 0), 2) == 400,
                f"balances={[(item.balance_before, item.balance_after) for item in all_entries]}",
            )

    print("\nTEST 3B: Repeat loan payroll completion")
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
            "Repeated loan payroll does not duplicate payslips or ledger entries",
            response.status_code in (200, 302)
            and run.status == "Completed"
            and len(slips) == 1
            and len(entries) == 1,
            f"HTTP={response.status_code}; "
            f"status={run.status}; payslips={len(slips)}; "
            f"ledger={len(entries)}",
        )

        record(
            "Repeated loan payroll does not deduct the loan twice",
            round(float(loan_row.total_paid or 0), 2) == 800
            and round(float(loan_row.outstanding_balance or 0), 2) == 400,
            f"total_paid={loan_row.total_paid}; "
            f"outstanding={loan_row.outstanding_balance}",
        )

        if len(entries) == 1:
            entry = entries[0]
            record(
                "Next repayment follows historical payment number 1",
                entry.payment_number == 2,
                f"payment_number={entry.payment_number}",
            )

    print("\nTEST 3C: Duplicate repayment reference protection")
    with app.app_context():
        original = LoanRepayment.query.filter_by(
            loan_application_id=loan_id,
            payroll_run_id=loan_run_id,
        ).first()

        if original is None or not original.reference:
            record(
                "Duplicate repayment reference is rejected and original is preserved",
                False,
                "Could not find the original committed repayment and reference.",
            )
        else:
            original_reference = original.reference

            duplicate = LoanRepayment(
                loan_application_id=original.loan_application_id,
                employee_id=original.employee_id,
                payroll_run_id=original.payroll_run_id,
                payslip_id=original.payslip_id,
                amount=original.amount,
                balance_before=original.balance_before,
                balance_after=original.balance_after,
                payment_number=original.payment_number,
                repayment_date=original.repayment_date,
                payment_method=original.payment_method,
                source=original.source,
                reference=original_reference,
                status=original.status,
                notes="Duplicate-reference regression test",
            )

            duplicate_rejected = False
            try:
                db.session.add(duplicate)
                db.session.flush()
            except IntegrityError:
                duplicate_rejected = True
                db.session.rollback()
            except Exception:
                db.session.rollback()
                raise
            else:
                # If the database unexpectedly accepts the duplicate,
                # remove the test insert without committing it.
                db.session.rollback()

            original_count = LoanRepayment.query.filter_by(
                reference=original_reference,
            ).count()

            record(
                "Duplicate repayment reference is rejected and original is preserved",
                duplicate_rejected and original_count == 1,
                f"duplicate_rejected={duplicate_rejected}; "
                f"original_reference_count={original_count}",
            )


    print("\nTEST 3D: Mid-transaction rollback")

    import app.routes as routes_module

    # Create a fresh, valid payroll run using the existing loan fixture.
    with app.app_context():
        tx_company = db.session.get(Company, company_a_id)
        tx_run = new_run(tx_company, "Mid-Transaction Rollback Test")
        new_input(tx_run, employee_loan)
        db.session.commit()
        tx_run_id = tx_run.id

    original_helper = routes_module.create_loan_repayment_ledger_entry
    injected_failure = {"raised": False}

    def fail_after_ledger_creation(*args, **kwargs):
        entry, created = original_helper(*args, **kwargs)

        if created:
            injected_failure["raised"] = True
            raise RuntimeError(
                "Intentional Phase 5 rollback-test failure"
            )

        return entry, created

    routes_module.create_loan_repayment_ledger_entry = (
        fail_after_ledger_creation
    )

    try:
        response = complete(tx_run_id)
    finally:
        # Always restore the original application function.
        routes_module.create_loan_repayment_ledger_entry = original_helper

    with app.app_context():
        tx_run = db.session.get(PayrollRun, tx_run_id)
        tx_loan = db.session.get(LoanApplication, loan_id)

        tx_slips = Payslip.query.filter_by(
            payroll_run_id=tx_run_id
        ).count()

        tx_entries = LoanRepayment.query.filter_by(
            loan_application_id=loan_id,
            payroll_run_id=tx_run_id,
        ).count()

        record(
            "Injected failure occurred after ledger creation",
            injected_failure["raised"],
            f"injected={injected_failure['raised']}",
        )

        record(
            "Mid-transaction failure rolls back all payroll changes",
            tx_run.status == "Approved"
            and tx_slips == 0
            and tx_entries == 0
            and round(float(tx_loan.total_paid or 0), 2) == 800
            and round(
                float(tx_loan.outstanding_balance or 0), 2
            ) == 400,
            f"HTTP={response.status_code}; "
            f"status={tx_run.status}; payslips={tx_slips}; "
            f"ledger={tx_entries}; paid={tx_loan.total_paid}; "
            f"outstanding={tx_loan.outstanding_balance}",
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

    print("\nTEST 5: Rollback after duplicate loan inputs")
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
            "Failed payroll rolls back payslips, ledger and loan balance",
            run.status == "Approved"
            and slip_count == 0
            and ledger_count == 0
            and round(float(loan_row.total_paid or 0), 2) == 200
            and round(float(loan_row.outstanding_balance or 0), 2)
            == 1000,
            f"HTTP={response.status_code}; status={run.status}; "
            f"payslips={slip_count}; ledger={ledger_count}; "
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

    print("\nTEST 7: Payment numbering after a historical gap")
    with app.app_context():
        gap_employee = Employee.query.filter_by(
            first_name="Normal",
            last_name="Employee",
        ).first()
        gap_run = PayrollRun.query.filter_by(
            pay_period="Normal Test",
        ).first()

        gap_payslip = Payslip.query.filter_by(
            payroll_run_id=gap_run.id,
            employee_id=gap_employee.id,
        ).first()

        gap_loan = make(
            LoanApplication,
            employee_id=gap_employee.id,
            reference="PHASE5-PAYMENT-GAP-LOAN",
            requested_amount=500,
            approved_amount=500,
            repayment_term="2 months",
            status="Disbursed",
            principal_amount=500,
            interest_amount=0,
            service_fee=0,
            total_repayable=500,
            scheduled_installment=100,
            total_paid=20,
            outstanding_balance=480,
            number_of_payments=5,
        )

        for number, reference in [
            (1, "PHASE5-GAP-HISTORICAL-1"),
            (3, "PHASE5-GAP-HISTORICAL-3"),
        ]:
            make(
                LoanRepayment,
                loan_application_id=gap_loan.id,
                employee_id=gap_employee.id,
                amount=10,
                balance_before=500,
                balance_after=490,
                payment_number=number,
                status="Completed",
                payment_method="Historical Test Payment",
                reference=reference,
                repayment_date=date(2026, 9, 30),
            )

        new_entry, created = create_loan_repayment_ledger_entry(
            gap_loan,
            gap_employee,
            gap_run,
            gap_payslip,
            50,
        )

        record(
            "Next payment number follows the highest existing number",
            created and new_entry.payment_number == 4,
            f"created={created}; payment_number={new_entry.payment_number}",
        )

        db.session.rollback()


except Exception as exc:
    script_error = True
    print("\n[TEST SCRIPT ERROR]", type(exc).__name__ + ":", exc)
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
    if failed or script_error:
        print("RESULT: FAILED — review test failures or the script error above.")
    else:
        print("RESULT: PASSED — all tests completed without script errors.")
    print("Isolated test run finished.")

    if failed or script_error:
        raise SystemExit(1)
