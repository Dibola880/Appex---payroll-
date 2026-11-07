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
    prefix="appex_company_admin_operational_",
    suffix=".db",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "company-admin-operational-test-only"

results = []
app = None
db = None


def record(name, passed, details=""):
    results.append((name, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


def run_test(name, callback):
    try:
        callback()
        record(name, True)
    except Exception as exc:
        record(name, False, repr(exc))
        traceback.print_exc()


try:
    from app import create_app, db
    from app import routes as routes_module
    from app.models import (
        Company,
        User,
        Employee,
        EmployeeInvitation,
        PayrollRun,
        PayrollInput,
        LoanApplication,
        SalesLead,
        ClientReferral,
    )

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        print("Database dialect:", db.engine.dialect.name)
        assert db.engine.dialect.name == "sqlite", (
            "Safety check failed: test database is not SQLite."
        )

        def make(Model, **values):
            columns = {column.name for column in Model.__table__.columns}
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

        # --------------------------------------------------------
        # ISOLATED TEST FIXTURES
        # --------------------------------------------------------

        company_a = make(
            Company,
            name="Operational Test Company A",
            client_status="Prospect",
            subscription_plan="Premium",
            subscription_status="Active",
        )

        company_b = make(
            Company,
            name="Operational Test Company B",
            client_status="Trial",
            subscription_plan="Free Trial",
            subscription_status="Trial",
        )

        admin_a = make(
            User,
            company_id=company_a.id,
            name="Company A Administrator",
            email="operational-admin-a@example.test",
            password_hash="test-hash",
            role="company_admin",
            is_active=True,
        )

        admin_b = make(
            User,
            company_id=company_b.id,
            name="Company B Administrator",
            email="operational-admin-b@example.test",
            password_hash="test-hash",
            role="company_admin",
            is_active=True,
        )

        employee_a = make(
            Employee,
            company_id=company_a.id,
            first_name="Company A",
            last_name="Employee",
            employee_number="OP-A-001",
            email="employee-a@example.test",
            monthly_salary=15000,
            status="Active",
        )

        employee_b = make(
            Employee,
            company_id=company_b.id,
            first_name="Company B",
            last_name="Employee",
            employee_number="OP-B-001",
            email="employee-b@example.test",
            monthly_salary=18000,
            status="Active",
        )

        foreign_loan = make(
            LoanApplication,
            employee_id=employee_b.id,
            reference="OP-FOREIGN-LOAN",
            requested_amount=500,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )

        foreign_lead = make(
            SalesLead,
            company_name="Company B Assigned Lead",
            contact_person="Company B Contact",
            email="company-b-lead@example.test",
            status="New Lead",
            assigned_to=admin_b.id,
        )

        foreign_referral = make(
            ClientReferral,
            referrer_company_id=company_b.id,
            referred_company_name="Company B Referral",
            referred_contact_person="Company B Contact",
            referred_email="company-b-referral@example.test",
            status="Submitted",
        )

        db.session.commit()

        client = app.test_client()

        def login_as(user):
            with client.session_transaction() as session:
                session["user_id"] = user.id

        def logout():
            with client.session_transaction() as session:
                session.clear()

        login_as(admin_a)

        # --------------------------------------------------------
        # A. EMPLOYEE CREATION, INVITATION AND TENANT OWNERSHIP
        # --------------------------------------------------------

        def test_employee_list():
            response = client.get("/employees")
            assert response.status_code == 200
            assert b"Company A" in response.data
            assert b"Company B" not in response.data

        run_test("Company administrator opens own employee list", test_employee_list)

        def test_create_employee():
            response = client.post(
                "/employees/new",
                data={
                    "employee_number": "OP-A-NEW-001",
                    "first_name": "New",
                    "last_name": "Employee",
                    "date_of_birth": "1995-04-12",
                    "email": "new-employee-a@example.test",
                    "job_title": "Test Officer",
                    "monthly_salary": "12500",
                },
            )
            assert response.status_code in (200, 302)

            created = Employee.query.filter_by(
                employee_number="OP-A-NEW-001"
            ).first()

            assert created is not None
            assert created.company_id == company_a.id

        run_test("New employee is created under Company A", test_create_employee)

        new_employee = Employee.query.filter_by(
            employee_number="OP-A-NEW-001"
        ).first()

        def test_invite_own_employee():
            response = client.get(
                f"/employees/{new_employee.id}/invite"
            )
            assert response.status_code in (200, 302)

            invitation = EmployeeInvitation.query.filter_by(
                employee_id=new_employee.id
            ).order_by(EmployeeInvitation.id.desc()).first()

            assert invitation is not None
            assert invitation.used is False
            assert new_employee.company_id == company_a.id

        run_test("Company administrator can invite own employee", test_invite_own_employee)

        invitation = EmployeeInvitation.query.filter_by(
            employee_id=new_employee.id
        ).order_by(EmployeeInvitation.id.desc()).first()

        def test_foreign_employee_invitation_denied():
            response = client.get(
                f"/employees/{employee_b.id}/invite"
            )
            assert response.status_code == 404

        run_test("Invitation for Company B employee is denied", test_foreign_employee_invitation_denied)

        def test_invitation_acceptance_preserves_company():
            assert invitation is not None

            logout()

            response = client.post(
                f"/invite/{invitation.token}",
                data={
                    "name": "New Employee A",
                    "email": "new-employee-login@example.test",
                    "password": "TestPassword123!",
                    "confirm_password": "TestPassword123!",
                },
            )

            assert response.status_code in (200, 302)

            db.session.expire_all()
            accepted_employee = db.session.get(Employee, new_employee.id)
            accepted_invitation = db.session.get(
                EmployeeInvitation,
                invitation.id,
            )

            linked_user = User.query.filter_by(
                email="new-employee-login@example.test"
            ).first()

            assert linked_user is not None
            assert linked_user.role == "employee"
            assert linked_user.company_id == company_a.id
            assert accepted_employee.user_id == linked_user.id
            assert accepted_invitation.used is True

            login_as(admin_a)

        run_test("Invitation acceptance preserves Company A ownership", test_invitation_acceptance_preserves_company)

        # --------------------------------------------------------
        # B. PAYROLL CREATION, REVIEW AND APPROVAL
        # --------------------------------------------------------

        created_payroll_id = None

        def test_payroll_creation_and_input_isolation():

            response = client.post(
                "/payroll",
                data={
                    "action": "draft",
                    "pay_period": "OPERATIONAL-TEST-2026-11",
                    "pay_date": "2026-11-30",
                    f"employee_{employee_a.id}_overtime": "250",
                    f"employee_{employee_b.id}_overtime": "999999",
                },
            )

            assert response.status_code in (200, 302)

            payroll = PayrollRun.query.filter_by(
                company_id=company_a.id,
                pay_period="OPERATIONAL-TEST-2026-11",
            ).first()

            assert payroll is not None
            assert payroll.company_id == company_a.id

            inputs = PayrollInput.query.filter_by(
                payroll_run_id=payroll.id
            ).all()

            assert inputs
            assert any(
                item.employee_id == employee_a.id
                for item in inputs
            )
            assert all(
                db.session.get(Employee, item.employee_id).company_id == company_a.id
                for item in inputs
            )

            assert not any(
                item.employee_id == employee_b.id
                for item in inputs
            )

            assert any(
                item.employee_id == employee_a.id
                and float(item.overtime or 0) == 250
                for item in inputs
            )

            db.session.flush()
            globals()["_operational_test_payroll_id"] = payroll.id

        run_test("Payroll creation includes only Company A employees", test_payroll_creation_and_input_isolation)

        payroll_id = globals().get("_operational_test_payroll_id")

        def test_foreign_payroll_detail_denied():
            foreign_payroll = make(
                PayrollRun,
                company_id=company_b.id,
                pay_period="OPERATIONAL-FOREIGN-2026-11",
                pay_date=date(2026, 11, 30),
                status="Draft",
            )
            db.session.commit()

            response = client.get(f"/payroll/{foreign_payroll.id}")
            assert response.status_code == 404

        run_test("Company B payroll detail is denied", test_foreign_payroll_detail_denied)

        def test_payroll_review_and_approval():
            assert payroll_id is not None

            response = client.post(
                f"/payroll/{payroll_id}/submit-review"
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            payroll = db.session.get(PayrollRun, payroll_id)
            assert payroll.status == "Review"

            review_page = client.get(
                f"/payroll/{payroll_id}/review"
            )
            assert review_page.status_code == 200

            response = client.post(
                f"/payroll/{payroll_id}/approve"
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            payroll = db.session.get(PayrollRun, payroll_id)
            assert payroll.status == "Approved"

        run_test("Company administrator can review and approve own payroll", test_payroll_review_and_approval)

        # --------------------------------------------------------
        # C. LOAN MANAGEMENT AND CROSS-COMPANY PROTECTION
        # --------------------------------------------------------

        own_loan_approve = make(
            LoanApplication,
            employee_id=employee_a.id,
            reference="OP-OWN-APPROVE",
            requested_amount=1200,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )

        own_loan_reject = make(
            LoanApplication,
            employee_id=employee_a.id,
            reference="OP-OWN-REJECT",
            requested_amount=800,
            status="Submitted",
            principal_amount=0,
            interest_amount=0,
            service_fee_amount=0,
            total_paid=0,
            outstanding_balance=0,
        )

        db.session.commit()

        def test_loan_list():
            response = client.get("/loans")
            assert response.status_code == 200
            assert b"OP-OWN-APPROVE" in response.data
            assert b"OP-FOREIGN-LOAN" not in response.data

        run_test("Company administrator sees only own-company loans", test_loan_list)

        def test_approve_and_disburse_own_loan():
            response = client.post(
                f"/loans/{own_loan_approve.id}/approve",
                data={
                    "approved_amount": "1000",
                    "approval_notes": "Operational test approval",
                },
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            loan = db.session.get(LoanApplication, own_loan_approve.id)
            assert loan.status == "Approved"
            assert float(loan.approved_amount) == 1000
            assert loan.reviewed_by == admin_a.id

            response = client.post(
                f"/loans/{own_loan_approve.id}/disburse",
                data={
                    "disbursement_reference": "OP-TEST-DISBURSE-001",
                },
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            loan = db.session.get(LoanApplication, own_loan_approve.id)
            assert loan.status == "Disbursed"
            assert loan.disbursement_reference == "OP-TEST-DISBURSE-001"

            original_reference = loan.disbursement_reference

            response = client.post(
                f"/loans/{own_loan_approve.id}/disburse",
                data={
                    "disbursement_reference": "OP-TEST-DISBURSE-SECOND",
                },
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            loan = db.session.get(LoanApplication, own_loan_approve.id)
            assert loan.status == "Disbursed"
            assert loan.disbursement_reference == original_reference

        run_test("Own loan approval, disbursement and repeat-disbursement protection", test_approve_and_disburse_own_loan)

        def test_reject_own_loan():
            response = client.post(
                f"/loans/{own_loan_reject.id}/reject",
                data={
                    "approval_notes": "Operational test rejection",
                },
            )
            assert response.status_code in (200, 302)

            db.session.expire_all()
            loan = db.session.get(LoanApplication, own_loan_reject.id)
            assert loan.status == "Rejected"
            assert loan.reviewed_by == admin_a.id

        run_test("Company administrator can reject own-company loan", test_reject_own_loan)

        def test_foreign_loan_approval_and_disbursement_denied():
            response = client.post(
                f"/loans/{foreign_loan.id}/approve",
                data={"approved_amount": "500"},
            )
            assert response.status_code == 404

            response = client.post(
                f"/loans/{foreign_loan.id}/disburse",
                data={"disbursement_reference": "FOREIGN-ATTEMPT"},
            )
            assert response.status_code == 404

            db.session.expire_all()
            loan = db.session.get(LoanApplication, foreign_loan.id)
            assert loan.status == "Submitted"
            assert loan.approved_amount is None
            assert loan.disbursement_reference is None

        run_test("Company B loan approval and disbursement are denied", test_foreign_loan_approval_and_disbursement_denied)

        # --------------------------------------------------------
        # D. INTEGRATION AND COMPANY ONBOARDING
        # --------------------------------------------------------

        def test_integration_page():
            response = client.get("/integration")
            assert response.status_code == 200

        run_test("Company administrator can view integration status", test_integration_page)

        def test_onboarding_updates_only_own_company():
            response = client.post(
                "/client-onboarding",
                data={
                    "company_name": "Company A Updated Name",
                    "registration_number": "REG-OP-A-001",
                    "contact_person": "A Contact",
                    "contact_phone": "0100000000",
                    "contact_email": "contact-a@example.test",
                    # These are deliberately submitted but must not
                    # change subscription administration fields.
                    "subscription_plan": "Enterprise",
                    "subscription_status": "Cancelled",
                },
            )

            assert response.status_code in (200, 302)

            db.session.expire_all()
            a = db.session.get(Company, company_a.id)
            b = db.session.get(Company, company_b.id)

            assert a.name == "Company A Updated Name"
            assert a.registration_number == "REG-OP-A-001"
            assert a.contact_person == "A Contact"
            assert a.contact_email == "contact-a@example.test"
            assert a.onboarding_completed is True

            assert a.subscription_plan == "Premium"
            assert a.subscription_status == "Active"

            assert b.name == "Operational Test Company B"
            assert b.subscription_plan == "Free Trial"
            assert b.subscription_status == "Trial"

        run_test("Onboarding changes own company only and ignores subscription changes", test_onboarding_updates_only_own_company)

        # --------------------------------------------------------
        # E. COMPANY-OWNED REFERRALS
        # --------------------------------------------------------

        def test_referral_list_is_company_scoped():
            captured = {}
            original_render_template = routes_module.render_template

            def capture_template(template_name, **context):
                captured["template_name"] = template_name
                captured["context"] = context
                return "template captured"

            routes_module.render_template = capture_template
            try:
                response = client.get("/referrals")
            finally:
                routes_module.render_template = original_render_template

            assert response.status_code == 200
            assert captured["template_name"] == "referrals.html"

            returned_referrals = captured["context"]["referrals"]
            assert all(
                referral.referrer_company_id == company_a.id
                for referral in returned_referrals
            )
            assert foreign_referral.id not in {
                referral.id for referral in returned_referrals
            }

        run_test("Referral list excludes Company B referrals", test_referral_list_is_company_scoped)

        def test_create_company_referral():
            response = client.post(
                "/referrals/new",
                data={
                    "referred_company_name": "Company A Referred Business",
                    "referred_contact_person": "Referral Contact",
                    "referred_email": "referral-a@example.test",
                    "referred_phone": "0110000000",
                },
            )

            assert response.status_code in (200, 302)

            referral = ClientReferral.query.filter_by(
                referred_email="referral-a@example.test"
            ).first()

            assert referral is not None
            assert referral.referrer_company_id == company_a.id

        run_test("New referral is owned by Company A", test_create_company_referral)

        # --------------------------------------------------------
        # F. INDIVIDUALLY ASSIGNED SALES LEADS
        # --------------------------------------------------------

        def test_lead_list_is_individually_scoped():
            captured = {}
            original_render_template = routes_module.render_template

            def capture_template(template_name, **context):
                captured["template_name"] = template_name
                captured["context"] = context
                return "template captured"

            routes_module.render_template = capture_template
            try:
                response = client.get("/leads")
            finally:
                routes_module.render_template = original_render_template

            assert response.status_code == 200
            assert captured["template_name"] == "leads.html"

            returned_leads = captured["context"]["leads"]
            assert all(
                lead.assigned_to == admin_a.id
                for lead in returned_leads
            )
            assert foreign_lead.id not in {
                lead.id for lead in returned_leads
            }
            assert captured["context"]["total_leads"] == len(returned_leads)

        run_test("Sales lead list shows only administrator's assigned leads", test_lead_list_is_individually_scoped)

        def test_create_own_lead():
            response = client.post(
                "/leads/new",
                data={
                    "company_name": "Company A New Prospect",
                    "contact_person": "Prospect Contact",
                    "email": "prospect-a@example.test",
                    "phone": "0120000000",
                    "registration_number": "LEAD-A-001",
                    "number_of_employees": "10",
                    "source": "Direct",
                    "notes": "Operational test lead",
                },
            )

            assert response.status_code in (200, 302)

            lead = SalesLead.query.filter_by(
                email="prospect-a@example.test"
            ).first()

            assert lead is not None
            assert lead.assigned_to == admin_a.id

        run_test("New sales lead is assigned to creating administrator", test_create_own_lead)

        def test_foreign_assigned_lead_cannot_be_modified():
            response = client.post(
                f"/leads/{foreign_lead.id}/status",
                data={"status": "New Lead"},
            )
            assert response.status_code == 404

            db.session.expire_all()
            lead = db.session.get(SalesLead, foreign_lead.id)
            assert lead.status == "New Lead"
            assert lead.assigned_to == admin_b.id

        run_test("Administrator cannot modify another user's assigned lead", test_foreign_assigned_lead_cannot_be_modified)

        # --------------------------------------------------------
        # G. ROLE BOUNDARIES
        # --------------------------------------------------------

        def test_platform_admin_not_company_operational_admin():
            platform_user = make(
                User,
                company_id=company_a.id,
                name="Platform Super Administrator",
                email="platform-super-admin@example.test",
                password_hash="test-hash",
                role="platform_super_admin",
                is_active=True,
            )
            db.session.commit()

            login_as(platform_user)
            response = client.get("/employees")
            assert response.status_code != 200

            login_as(admin_a)

        run_test("Platform super administrator is not granted company operational access", test_platform_admin_not_company_operational_admin)

        def test_legacy_admin_role_preserved():
            legacy_admin = make(
                User,
                company_id=company_a.id,
                name="Legacy Administrator",
                email="legacy-admin-operational@example.test",
                password_hash="test-hash",
                role="admin",
                is_active=True,
            )
            db.session.commit()

            login_as(legacy_admin)
            response = client.get("/employees")
            assert response.status_code == 200

            login_as(admin_a)

        run_test("Legacy admin operational access remains intact", test_legacy_admin_role_preserved)

        # --------------------------------------------------------
        # FINAL SUMMARY
        # --------------------------------------------------------

        passed = sum(1 for _, ok in results if ok)
        failed = len(results) - passed

        print("\n========================================")
        print("COMPANY ADMIN OPERATIONAL TEST SUMMARY")
        print("========================================")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total:  {len(results)}")

        if failed:
            print("\nFailed tests:")
            for name, ok in results:
                if not ok:
                    print(" -", name)

        print("========================================")

except Exception:
    traceback.print_exc()
    results.append(("TEST SCRIPT SETUP", False))

finally:
    if app is not None and db is not None:
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            traceback.print_exc()

    if os.path.exists(DB_PATH):
        try:
            os.unlink(DB_PATH)
        except OSError:
            pass

if not results or any(not passed for _, passed in results):
    sys.exit(1)

sys.exit(0)
