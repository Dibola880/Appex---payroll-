import os
import sys
import tempfile
import traceback
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
                "First loan repayment has payment number 1",
                entry.payment_number == 1,
                f"payment_number={entry.payment_number}",
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


    print("\nTEST 7: Loan approval")
    with app.app_context():
        approval_loan = make(
            LoanApplication,
            employee_id=loan_employee_id,
            reference="PHASE5-APPROVAL-TEST",
            requested_amount=1000,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )
        approval_loan_id = approval_loan.id
        db.session.commit()

    login(employer_id)
    response = client.post(
        f"/loans/{approval_loan_id}/approve",
        data={
            "approved_amount": "800",
            "approval_notes": "Regression test approval",
        },
    )

    with app.app_context():
        row = db.session.get(LoanApplication, approval_loan_id)
        record(
            "Valid approval records amount, status and reviewer",
            response.status_code == 302
            and row.status == "Approved"
            and round(float(row.approved_amount or 0), 2) == 800
            and round(float(row.total_repayable or 0), 2) == 800
            and round(float(row.outstanding_balance or 0), 2) == 800
            and row.reviewed_by == employer_id
            and row.approval_notes == "Regression test approval",
            f"HTTP={response.status_code}; status={row.status}; "
            f"approved={row.approved_amount}; "
            f"outstanding={row.outstanding_balance}",
        )

    print("\nTEST 8: Invalid approval amount")
    with app.app_context():
        invalid_loan = make(
            LoanApplication,
            employee_id=loan_employee_id,
            reference="PHASE5-INVALID-APPROVAL-TEST",
            requested_amount=500,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )
        invalid_loan_id = invalid_loan.id
        db.session.commit()

    login(employer_id)
    response = client.post(
        f"/loans/{invalid_loan_id}/approve",
        data={"approved_amount": "501"},
    )

    with app.app_context():
        row = db.session.get(LoanApplication, invalid_loan_id)
        record(
            "Approval above requested amount is rejected",
            response.status_code == 302
            and row.status == "Submitted"
            and row.approved_amount is None,
            f"HTTP={response.status_code}; status={row.status}; "
            f"approved={row.approved_amount}",
        )

    print("\nTEST 9: Loan rejection")
    with app.app_context():
        rejection_loan = make(
            LoanApplication,
            employee_id=loan_employee_id,
            reference="PHASE5-REJECTION-TEST",
            requested_amount=700,
            status="Under Review",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )
        rejection_loan_id = rejection_loan.id
        db.session.commit()

    login(employer_id)
    response = client.post(
        f"/loans/{rejection_loan_id}/reject",
        data={"rejection_reason": "Regression test rejection"},
    )

    with app.app_context():
        row = db.session.get(LoanApplication, rejection_loan_id)
        record(
            "Rejection records status, reviewer and reason",
            response.status_code == 302
            and row.status == "Rejected"
            and row.reviewed_by == employer_id
            and row.approval_notes == "Regression test rejection",
            f"HTTP={response.status_code}; status={row.status}; "
            f"reviewer={row.reviewed_by}; notes={row.approval_notes}",
        )

    print("\nTEST 10: Loan disbursement")
    with app.app_context():
        disbursement_loan = make(
            LoanApplication,
            employee_id=loan_employee_id,
            reference="PHASE5-DISBURSE-TEST",
            requested_amount=900,
            approved_amount=900,
            status="Approved",
            principal_amount=900,
            interest_amount=100,
            service_fee_amount=0,
            total_repayable=1000,
            total_paid=0,
            outstanding_balance=900,
        )
        disbursement_loan_id = disbursement_loan.id
        db.session.commit()

    login(employer_id)
    response = client.post(
        f"/loans/{disbursement_loan_id}/disburse",
        data={"disbursement_reference": "PHASE5-DISB-REF-001"},
    )

    with app.app_context():
        row = db.session.get(LoanApplication, disbursement_loan_id)
        record(
            "Approved loan disburses with reference and balance",
            response.status_code == 302
            and row.status == "Disbursed"
            and row.disbursed_at is not None
            and row.disbursement_reference == "PHASE5-DISB-REF-001"
            and round(float(row.outstanding_balance or 0), 2) == 1000,
            f"HTTP={response.status_code}; status={row.status}; "
            f"reference={row.disbursement_reference}; "
            f"outstanding={row.outstanding_balance}",
        )
        original_reference = row.disbursement_reference
        original_disbursed_at = row.disbursed_at

    print("\nTEST 11: Repeat disbursement")
    login(employer_id)
    response = client.post(
        f"/loans/{disbursement_loan_id}/disburse",
        data={"disbursement_reference": "PHASE5-DISB-REF-SECOND"},
    )

    with app.app_context():
        row = db.session.get(LoanApplication, disbursement_loan_id)
        record(
            "Repeat disbursement does not replace original disbursement",
            response.status_code == 302
            and row.status == "Disbursed"
            and row.disbursement_reference == original_reference
            and row.disbursed_at == original_disbursed_at,
            f"HTTP={response.status_code}; status={row.status}; "
            f"reference={row.disbursement_reference}",
        )

    print("\nTEST 12: Cross-company loan access")
    with app.app_context():
        foreign_company_id = db.session.query(Company.id).filter_by(
            name="Phase 5 Test Company B",
        ).scalar()

        if foreign_company_id is None:
            raise RuntimeError(
                "Cross-company fixture company could not be found."
            )

        foreign_employee_id = db.session.query(Employee.id).filter_by(
            first_name="Foreign",
            last_name="Employee",
            company_id=foreign_company_id,
        ).scalar()

        if foreign_employee_id is None:
            raise RuntimeError(
                "Cross-company fixture employee could not be found."
            )

        foreign_loan = make(
            LoanApplication,
            employee_id=foreign_employee_id,
            reference="PHASE5-FOREIGN-LOAN-TEST",
            requested_amount=600,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )
        foreign_loan_id = foreign_loan.id
        db.session.commit()

    login(employer_id)
    response = client.post(
        f"/loans/{foreign_loan_id}/approve",
        data={"approved_amount": "600"},
    )

    with app.app_context():
        row = db.session.get(LoanApplication, foreign_loan_id)
        record(
            "Company A cannot approve Company B loan",
            response.status_code == 404
            and row.status == "Submitted"
            and row.approved_amount is None,
            f"HTTP={response.status_code}; status={row.status}; "
            f"approved={row.approved_amount}",
        )

except Exception as exc:
    print("\n[TEST SCRIPT ERROR]", type(exc).__name__ + ":", exc)
    traceback.print_exc()
    results.append((
        "Test script completed without unexpected exceptions",
        False,
    ))

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
    else:
        print("RESULT: PASSED — all tests completed without script errors.")
    print("Isolated test run finished.")

if failed:
    sys.exit(1)
sys.exit(0)
