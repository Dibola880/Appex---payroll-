"""Isolated behavioral tests for accounting setup and lifecycle services.

Safety:
- Uses a disposable SQLite database.
- Does not run migrations.
- Does not access the configured production database.
- Does not modify production application source.
"""

import os
import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# Establish an isolated database BEFORE importing the application.
fd, DB_PATH = tempfile.mkstemp(
    prefix="appex_accounting_lifecycle_",
    suffix=".sqlite",
)
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "isolated-accounting-lifecycle-tests"

RESULTS = []

# Make the repository root importable when this file runs directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def record(name, passed, details=""):
    RESULTS.append((name, bool(passed), details))
    status = "PASS" if passed else "FAIL"
    suffix = f" — {details}" if details else ""
    print(f"[{status}] {name}{suffix}")


def must_raise(callback, expected_type):
    try:
        callback()
    except expected_type as exc:
        return exc
    except Exception as exc:
        raise AssertionError(
            f"Expected {expected_type.__name__}, "
            f"received {type(exc).__name__}: {exc}"
        ) from exc

    raise AssertionError(
        f"Expected {expected_type.__name__}, but no exception was raised."
    )


def make(model, **values):
    allowed = {column.key for column in model.__table__.columns}
    filtered = {key: value for key, value in values.items() if key in allowed}
    obj = model(**filtered)
    db.session.add(obj)
    db.session.flush()
    return obj


try:
    from app import create_app, db
    from app.models import (
        Account,
        AccountingPeriod,
        AccountingPeriodEvent,
        Company,
        CompanySubscription,
        FinancialYear,
        SubscriptionPlan,
        User,
    )
    from app.accounting_chart import prepare_company_accounts
    from app.accounting_setup import (
        AccountingSetupError,
        setup_company_accounting,
    )
    from app.accounting_lifecycle_service import (
        AccountingLifecycleServiceError,
        close_accounting_period,
        reopen_accounting_period,
        close_financial_year,
        reopen_financial_year,
    )
    from app.accounting_period_lifecycle import AccountingPeriodLifecycleError

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            raise RuntimeError(
                "SAFETY STOP: accounting tests require disposable SQLite."
            )

        print("Database dialect:", db.engine.dialect.name)
        print("Disposable database:", DB_PATH)

        now = datetime.utcnow()
        fixed_time = datetime(2026, 11, 19, 10, 30, 0)

        def make_company(label, accounting=True):
            company = make(
                Company,
                name=label,
            )

            plan = make(
                SubscriptionPlan,
                code=f"TEST-{company.id}",
                name=f"Test Plan {company.id}",
                feature_config={
                    "features": {"accounting": accounting}
                },
                is_active=True,
            )

            if accounting:
                make(
                    CompanySubscription,
                    company_id=company.id,
                    plan_id=plan.id,
                    status="Active",
                    billing_interval="monthly",
                    currency="ZAR",
                    amount=0,
                    starts_at=now - timedelta(days=1),
                    current_period_start=now - timedelta(days=1),
                    current_period_end=now + timedelta(days=30),
                    is_current=True,
                )

            actor = make(
                User,
                company_id=company.id,
                name=f"Accounting Admin {company.id}",
                email=f"accounting-admin-{company.id}@example.test",
                password_hash="isolated-test-hash",
                role="company_admin",
                is_active=True,
            )

            return company, actor

        def setup(company, actor, name="FY 2026/2027"):
            return setup_company_accounting(
                company_id=company.id,
                actor_id=actor.id,
                financial_year_name=name,
                start_date=date(2026, 3, 15),
                end_date=date(2027, 2, 28),
            )

        company_a, admin_a = make_company("Accounting Test Company A")
        company_b, admin_b = make_company("Accounting Test Company B")
        no_entitlement_company, no_entitlement_admin = make_company(
            "Accounting Test Without Entitlement",
            accounting=False,
        )

        employer_a = make(
            User,
            company_id=company_a.id,
            name="Non-admin User",
            email="non-admin-accounting@example.test",
            password_hash="isolated-test-hash",
            role="employer",
            is_active=True,
        )

        # ------------------------------------------------------------
        # 1. Successful initial setup and monthly schedule.
        # ------------------------------------------------------------

        result = setup(company_a, admin_a)

        year = FinancialYear.query.filter_by(
            company_id=company_a.id
        ).one()

        periods = (
            AccountingPeriod.query
            .filter_by(company_id=company_a.id, financial_year_id=year.id)
            .order_by(AccountingPeriod.period_number)
            .all()
        )

        opening_year_events = AccountingPeriodEvent.query.filter_by(
            company_id=company_a.id,
            financial_year_id=year.id,
            event_type="opened",
        ).count()

        opening_period_events = AccountingPeriodEvent.query.filter(
            AccountingPeriodEvent.company_id == company_a.id,
            AccountingPeriodEvent.accounting_period_id.isnot(None),
            AccountingPeriodEvent.event_type == "opened",
        ).count()

        assert result["already_configured"] is False
        assert len(periods) == 12
        assert periods[0].start_date == date(2026, 3, 15)
        assert periods[0].end_date == date(2026, 3, 31)
        assert periods[-1].start_date == date(2027, 2, 1)
        assert periods[-1].end_date == date(2027, 2, 28)
        assert [p.period_number for p in periods] == list(range(1, 13))
        assert all(p.status == "open" for p in periods)
        assert opening_year_events == 1
        assert opening_period_events == 12
        assert Account.query.filter_by(company_id=company_a.id).count() > 0

        record(
            "Initial setup creates chart, financial year, 12 periods and opening audit events",
            True,
        )

        # ------------------------------------------------------------
        # 2. Idempotent retry and customized account preservation.
        # ------------------------------------------------------------

        account = Account.query.filter_by(
            company_id=company_a.id
        ).order_by(Account.id).first()

        original_account_id = account.id
        account.name = "Customized Test Account"
        account.account_code = "CUSTOM-TEST-001"
        db.session.flush()

        accounts_before = Account.query.filter_by(
            company_id=company_a.id
        ).count()
        periods_before = AccountingPeriod.query.filter_by(
            company_id=company_a.id
        ).count()
        events_before = AccountingPeriodEvent.query.filter_by(
            company_id=company_a.id
        ).count()

        retry_result = setup(company_a, admin_a)

        db.session.expire_all()

        preserved_account = db.session.get(Account, original_account_id)

        assert retry_result["already_configured"] is True
        assert Account.query.filter_by(company_id=company_a.id).count() == accounts_before
        assert AccountingPeriod.query.filter_by(company_id=company_a.id).count() == periods_before
        assert AccountingPeriodEvent.query.filter_by(company_id=company_a.id).count() == events_before
        assert preserved_account.name == "Customized Test Account"
        assert preserved_account.account_code == "CUSTOM-TEST-001"

        record(
            "Exact retry is idempotent and preserves customized account details",
            True,
        )

        # ------------------------------------------------------------
        # 3. Conflicting financial-year name must be rejected.
        # ------------------------------------------------------------

        years_before = FinancialYear.query.filter_by(
            company_id=company_a.id
        ).count()

        conflict_error = must_raise(
            lambda: setup_company_accounting(
                company_id=company_a.id,
                actor_id=admin_a.id,
                financial_year_name="FY 2026/2027",
                start_date=date(2027, 3, 1),
                end_date=date(2028, 2, 29),
            ),
            AccountingSetupError,
        )

        assert FinancialYear.query.filter_by(
            company_id=company_a.id
        ).count() == years_before

        record(
            "Reusing an existing financial-year name for a different date range is rejected",
            True,
            str(conflict_error),
        )

        # ------------------------------------------------------------
        # 4. Chart account-code conflict must not partially set up.
        # ------------------------------------------------------------

        conflict_company, conflict_admin = make_company(
            "Accounting Test Chart Conflict"
        )

        template = next(
            item
            for item in prepare_company_accounts(conflict_company.id)
            if item.get("parent_code") is None
        )

        make(
            Account,
            company_id=conflict_company.id,
            account_code=template["account_code"],
            name="Conflicting Custom Account",
            account_type=template["account_type"],
            normal_balance=template["normal_balance"],
            parent_id=None,
            system_code="CUSTOM_CONFLICT_SYSTEM_CODE",
            is_active=True,
            allow_manual_posting=True,
        )

        # Persist the deliberate conflict fixture before the service transaction.
        db.session.commit()

        must_raise(
            lambda: setup(conflict_company, conflict_admin),
            AccountingSetupError,
        )

        assert FinancialYear.query.filter_by(
            company_id=conflict_company.id
        ).count() == 0

        assert AccountingPeriod.query.filter_by(
            company_id=conflict_company.id
        ).count() == 0

        assert AccountingPeriodEvent.query.filter_by(
            company_id=conflict_company.id
        ).count() == 0

        assert Account.query.filter_by(
            company_id=conflict_company.id
        ).count() == 1

        record(
            "Chart account-code conflict is rejected without partial setup",
            True,
        )

        # ------------------------------------------------------------
        # 5. Setup authorization and entitlement checks.
        # ------------------------------------------------------------

        must_raise(
            lambda: setup_company_accounting(
                company_id=company_a.id,
                actor_id=admin_b.id,
                financial_year_name="Unauthorized Year",
                start_date=date(2026, 3, 1),
                end_date=date(2027, 2, 28),
            ),
            AccountingSetupError,
        )

        must_raise(
            lambda: setup_company_accounting(
                company_id=company_a.id,
                actor_id=employer_a.id,
                financial_year_name="Wrong Role Year",
                start_date=date(2026, 3, 1),
                end_date=date(2027, 2, 28),
            ),
            AccountingSetupError,
        )

        must_raise(
            lambda: setup_company_accounting(
                company_id=no_entitlement_company.id,
                actor_id=no_entitlement_admin.id,
                financial_year_name="No Entitlement Year",
                start_date=date(2026, 3, 1),
                end_date=date(2027, 2, 28),
            ),
            AccountingSetupError,
        )

        assert FinancialYear.query.filter_by(
            company_id=company_a.id
        ).count() == 1

        assert FinancialYear.query.filter_by(
            company_id=no_entitlement_company.id
        ).count() == 0

        record(
            "Setup rejects foreign administrators, wrong roles and missing accounting entitlement",
            True,
        )

        # ------------------------------------------------------------
        # 6. Period and financial-year lifecycle.
        # ------------------------------------------------------------

        periods = (
            AccountingPeriod.query
            .filter_by(company_id=company_a.id, financial_year_id=year.id)
            .order_by(AccountingPeriod.period_number)
            .all()
        )

        first_period = periods[0]

        close_accounting_period(
            company_a.id,
            first_period.id,
            admin_a.id,
            "Close first test period",
            fixed_time,
        )

        assert db.session.get(
            AccountingPeriod, first_period.id
        ).status == "closed"

        # A financial year cannot close while any period remains open.
        must_raise(
            lambda: close_financial_year(
                company_a.id,
                year.id,
                admin_a.id,
                "Premature year close",
                fixed_time,
            ),
            AccountingPeriodLifecycleError,
        )

        assert db.session.get(FinancialYear, year.id).status == "open"

        for period in periods[1:]:
            close_accounting_period(
                company_a.id,
                period.id,
                admin_a.id,
                f"Close period {period.period_number}",
                fixed_time,
            )

        close_financial_year(
            company_a.id,
            year.id,
            admin_a.id,
            "All periods closed",
            fixed_time,
        )

        db.session.expire_all()

        assert db.session.get(FinancialYear, year.id).status == "closed"
        assert all(
            item.status == "closed"
            for item in AccountingPeriod.query.filter_by(
                company_id=company_a.id,
                financial_year_id=year.id,
            ).all()
        )

        reopen_financial_year(
            company_a.id,
            year.id,
            admin_a.id,
            "Reopen test financial year",
            fixed_time + timedelta(minutes=1),
        )

        db.session.expire_all()

        assert db.session.get(FinancialYear, year.id).status == "open"
        assert all(
            item.status == "closed"
            for item in AccountingPeriod.query.filter_by(
                company_id=company_a.id,
                financial_year_id=year.id,
            ).all()
        )

        reopen_accounting_period(
            company_a.id,
            first_period.id,
            admin_a.id,
            "Reopen first test period",
            fixed_time + timedelta(minutes=2),
        )

        db.session.expire_all()

        assert db.session.get(
            AccountingPeriod, first_period.id
        ).status == "open"

        assert db.session.get(FinancialYear, year.id).status == "open"

        record(
            "Period/year close ordering, year reopen and individual period reopen work correctly",
            True,
        )

        # ------------------------------------------------------------
        # 7. Lifecycle tenant isolation and authorization.
        # ------------------------------------------------------------

        must_raise(
            lambda: close_accounting_period(
                company_a.id,
                first_period.id,
                admin_b.id,
                "Foreign administrator attempt",
                fixed_time,
            ),
            AccountingLifecycleServiceError,
        )

        must_raise(
            lambda: close_accounting_period(
                company_a.id,
                first_period.id,
                employer_a.id,
                "Wrong role attempt",
                fixed_time,
            ),
            AccountingLifecycleServiceError,
        )

        assert db.session.get(
            AccountingPeriod, first_period.id
        ).status == "open"

        record(
            "Lifecycle operations reject foreign and non-administrator actors without mutation",
            True,
        )

        # ------------------------------------------------------------
        # 8. Lifecycle entitlement enforcement.
        # ------------------------------------------------------------

        must_raise(
            lambda: close_accounting_period(
                no_entitlement_company.id,
                999999,
                no_entitlement_admin.id,
                "No entitlement attempt",
                fixed_time,
            ),
            AccountingLifecycleServiceError,
        )

        record(
            "Lifecycle operations enforce accounting entitlement",
            True,
        )

        # ------------------------------------------------------------
        # 9. Incomplete opening audit history blocks idempotent setup.
        # ------------------------------------------------------------

        opening_event = AccountingPeriodEvent.query.filter_by(
            company_id=company_a.id,
            accounting_period_id=periods[1].id,
            event_type="opened",
        ).one()

        db.session.delete(opening_event)
        db.session.commit()

        must_raise(
            lambda: setup(company_a, admin_a),
            AccountingSetupError,
        )

        assert FinancialYear.query.filter_by(
            company_id=company_a.id
        ).count() == 1

        assert AccountingPeriod.query.filter_by(
            company_id=company_a.id
        ).count() == 12

        record(
            "Incomplete opening audit history prevents an unsafe idempotent retry",
            True,
        )

except Exception as exc:
    record(
        "TEST HARNESS / UNEXPECTED ERROR",
        False,
        f"{type(exc).__name__}: {exc}",
    )
    traceback.print_exc()

finally:
    try:
        if "db" in globals() and "app" in globals():
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    except Exception:
        traceback.print_exc()

    try:
        if os.path.exists(DB_PATH):
            os.unlink(DB_PATH)
    except OSError as exc:
        print("WARNING: Could not remove disposable SQLite file:", exc)

    print()
    print("===== ACCOUNTING SETUP / LIFECYCLE TEST SUMMARY =====")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("Production database and migrations were not used.")

    if failed:
        sys.exit(1)
    if not RESULTS:
        sys.exit(1)

    print("RESULT: PASS")
