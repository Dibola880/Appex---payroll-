import os
import sys
import tempfile
import traceback
import calendar
from pathlib import Path
from datetime import date
from decimal import Decimal

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

fd, DB_PATH = tempfile.mkstemp(prefix="appex_journal_test_", suffix=".db")
os.close(fd)
os.unlink(DB_PATH)

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["SECRET_KEY"] = "journal-isolated-test-only"

app = None
db = None
results = []
script_error = False


def record(name, passed, details=""):
    results.append((name, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if details:
        print("   ", details)


def expect_error(callback):
    try:
        callback()
    except Exception as exc:
        return True, f"{type(exc).__name__}: {exc}"
    return False, "Expected operation to reject the invalid request."


try:
    from app import create_app, db
    from app.models import (
        Company,
        User,
        Account,
        FinancialYear,
        AccountingPeriod,
        JournalEntry,
        JournalLine,
        JournalAuditEvent,
    )
    from app.journal_service import (
        create_journal,
        update_journal,
        post_journal,
        create_reversal,
        post_reversal,
        journal_draft_snapshot,
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
            obj = Model(**{
                key: value for key, value in values.items()
                if key in columns
            })
            db.session.add(obj)
            db.session.flush()
            return obj

        company_a = make(Company, name="Journal Test Company A")
        company_b = make(Company, name="Journal Test Company B")

        actor_a = make(
            User,
            company_id=company_a.id,
            name="Journal Employer A",
            email="journal-employer-a@example.test",
            password_hash="isolated-test-hash",
            role="employer",
            is_active=True,
        )
        actor_b = make(
            User,
            company_id=company_b.id,
            name="Journal Employer B",
            email="journal-employer-b@example.test",
            password_hash="isolated-test-hash",
            role="employer",
            is_active=True,
        )

        debit_a = make(
            Account,
            company_id=company_a.id,
            account_code="J100",
            name="Test Expense A",
            account_type="expense",
            normal_balance="debit",
            is_active=True,
            allow_manual_posting=True,
        )
        credit_a = make(
            Account,
            company_id=company_a.id,
            account_code="J200",
            name="Test Liability A",
            account_type="liability",
            normal_balance="credit",
            is_active=True,
            allow_manual_posting=True,
        )
        debit_b = make(
            Account,
            company_id=company_b.id,
            account_code="J100",
            name="Test Expense B",
            account_type="expense",
            normal_balance="debit",
            is_active=True,
            allow_manual_posting=True,
        )
        credit_b = make(
            Account,
            company_id=company_b.id,
            account_code="J200",
            name="Test Liability B",
            account_type="liability",
            normal_balance="credit",
            is_active=True,
            allow_manual_posting=True,
        )

        def make_calendar(company):
            year = make(
                FinancialYear,
                company_id=company.id,
                name="Journal Test FY 2026",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                status="open",
            )
            periods = []
            for month in range(1, 13):
                start = date(2026, month, 1)
                end = date(2026, month, calendar.monthrange(2026, month)[1])
                period = make(
                    AccountingPeriod,
                    company_id=company.id,
                    financial_year_id=year.id,
                    period_number=month,
                    name=f"2026-{month:02d}",
                    start_date=start,
                    end_date=end,
                    status="open",
                )
                periods.append(period)
            return year, periods

        year_a, periods_a = make_calendar(company_a)
        year_b, periods_b = make_calendar(company_b)

        # Preserve shared fixtures across individual test rollbacks.
        # This commit is confined to the disposable SQLite test database.
        db.session.commit()

        period_a = periods_a[0]

        def journal_lines(debit_account, credit_account, amount="100.00"):
            return [
                {
                    "line_number": 1,
                    "account_id": debit_account.id,
                    "description": "Test debit",
                    "debit": Decimal(amount),
                    "credit": Decimal("0.00"),
                },
                {
                    "line_number": 2,
                    "account_id": credit_account.id,
                    "description": "Test credit",
                    "debit": Decimal("0.00"),
                    "credit": Decimal(amount),
                },
            ]

        def create_a_draft(number, lines=None, period=None):
            return create_journal(
                company_id=company_a.id,
                actor_id=actor_a.id,
                journal_number=number,
                journal_date=date(2026, 1, 15),
                description="Journal service test",
                currency="ZAR",
                lines=lines or journal_lines(debit_a, credit_a),
                accounting_period_id=(period or period_a).id,
            )

        # 1. Draft creation and audit attribution.
        draft = create_a_draft("JT-001")
        db.session.flush()
        created_events = JournalAuditEvent.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=draft.id,
            event_type="created",
        ).all()
        record(
            "Draft creation records creator and created audit event",
            draft.status == "draft"
            and draft.created_by_id == actor_a.id
            and len(created_events) == 1
            and created_events[0].performed_by_id == actor_a.id,
            f"journal_id={draft.id}; created_events={len(created_events)}",
        )

        # 2. Draft update and optimistic concurrency.
        old_snapshot = journal_draft_snapshot(draft)
        updated = update_journal(
            company_id=company_a.id,
            journal_id=draft.id,
            actor_id=actor_a.id,
            lines=journal_lines(debit_a, credit_a, "125.00"),
            description="Updated journal test",
            reason="Testing draft update",
            expected_snapshot=old_snapshot,
        )
        db.session.flush()
        updated_snapshot = journal_draft_snapshot(updated)
        update_events = JournalAuditEvent.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=draft.id,
            event_type="updated",
        ).all()
        record(
            "Draft update changes draft and attributes audit event",
            updated.description == "Updated journal test"
            and len(update_events) == 1
            and update_events[0].performed_by_id == actor_a.id,
            f"update_events={len(update_events)}",
        )

        stale_ok, stale_details = expect_error(lambda: update_journal(
            company_id=company_a.id,
            journal_id=draft.id,
            actor_id=actor_a.id,
            lines=journal_lines(debit_a, credit_a, "150.00"),
            expected_snapshot=old_snapshot,
        ))
        record(
            "Stale draft snapshot is rejected",
            stale_ok,
            stale_details,
        )

        # Reload after rollback so later checks use persisted state.
        draft = db.session.get(JournalEntry, draft.id)

        # 3. Posting and period validation.
        postable = create_a_draft("JT-002")
        posted = post_journal(
            company_id=company_a.id,
            journal_id=postable.id,
            actor_id=actor_a.id,
        )
        db.session.flush()
        post_events = JournalAuditEvent.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=postable.id,
            event_type="posted",
        ).all()
        record(
            "Valid draft posts into its open accounting period",
            posted.status == "posted"
            and posted.accounting_period_id == period_a.id
            and posted.posted_by_id == actor_a.id
            and len(post_events) == 1
            and post_events[0].performed_by_id == actor_a.id,
            f"status={posted.status}; period_id={posted.accounting_period_id}",
        )

        closed_period_draft = create_a_draft("JT-003")
        period_a.status = "closed"
        db.session.flush()
        closed_ok, closed_details = expect_error(lambda: post_journal(
            company_id=company_a.id,
            journal_id=closed_period_draft.id,
            actor_id=actor_a.id,
        ))
        record(
            "Posting is rejected when its accounting period is closed",
            closed_ok,
            closed_details,
        )

        # Restore the test period to open for reversal tests.
        period_a = db.session.get(AccountingPeriod, period_a.id)
        period_a.status = "open"
        db.session.flush()

        # 4. Reversal creation and duplicate-reversal protection.
        original = create_a_draft("JT-004")
        original = post_journal(
            company_id=company_a.id,
            journal_id=original.id,
            actor_id=actor_a.id,
        )
        reversal = create_reversal(
            company_id=company_a.id,
            original_journal_id=original.id,
            actor_id=actor_a.id,
            reversal_journal_number="JT-004-R1",
            reversal_date=date(2026, 1, 20),
            reason="Test reversal",
        )
        db.session.flush()
        record(
            "Reversal draft references the posted original",
            reversal.status == "draft"
            and reversal.reversal_of_id == original.id
            and reversal.source_type == "reversal"
            and reversal.source_id == original.id,
            f"reversal_id={reversal.id}; original_id={original.id}",
        )

        duplicate_ok, duplicate_details = expect_error(
            lambda: create_reversal(
                company_id=company_a.id,
                original_journal_id=original.id,
                actor_id=actor_a.id,
                reversal_journal_number="JT-004-R2",
                reversal_date=date(2026, 1, 21),
                reason="Duplicate reversal attempt",
            )
        )
        # The expected service-level rejection makes no database changes.
        # Do not roll back the earlier original and reversal test fixtures.
        record(
            "A second reversal for the same original is rejected",
            duplicate_ok,
            duplicate_details,
        )

        # Reload reversal and original after rollback.
        original = db.session.get(JournalEntry, original.id)
        reversal = db.session.get(JournalEntry, reversal.id)

        # 5. Exact opposite-line validation and reversal posting.
        original_lines = JournalLine.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=original.id,
        ).order_by(JournalLine.line_number).all()
        reversal_lines = JournalLine.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=reversal.id,
        ).order_by(JournalLine.line_number).all()

        exact_mirror = (
            len(original_lines) == len(reversal_lines)
            and all(
                reverse_line.account_id == original_line.account_id
                and reverse_line.line_number == original_line.line_number
                and reverse_line.debit == original_line.credit
                and reverse_line.credit == original_line.debit
                and reverse_line.description == original_line.description
                for original_line, reverse_line
                in zip(original_lines, reversal_lines)
            )
        )
        record(
            "Reversal draft contains exact opposite lines",
            exact_mirror,
            f"original_lines={len(original_lines)}; reversal_lines={len(reversal_lines)}",
        )

        # Alter a reversal line without breaking the debit/credit balance.
        # The posting service must compare it to the original, not just balance.
        reversal_lines[0].description = "Tampered reversal description"
        db.session.flush()
        tamper_ok, tamper_details = expect_error(lambda: post_reversal(
            company_id=company_a.id,
            original_journal_id=original.id,
            reversal_journal_id=reversal.id,
            actor_id=actor_a.id,
            reason="Attempt to post altered reversal",
        ))
        record(
            "Reversal posting rejects altered opposite-line details",
            tamper_ok,
            tamper_details,
        )

        # Restore only the deliberately altered line. A full rollback here
        # would also erase the uncommitted original and reversal fixtures.
        reversal_lines = JournalLine.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=reversal.id,
        ).order_by(JournalLine.line_number).all()
        for original_line, reversal_line in zip(original_lines, reversal_lines):
            reversal_line.description = original_line.description
        db.session.flush()

        reversed_original, posted_reversal = post_reversal(
            company_id=company_a.id,
            original_journal_id=original.id,
            reversal_journal_id=reversal.id,
            actor_id=actor_a.id,
            reason="Verified test reversal",
        )
        db.session.flush()
        reversal_audits = JournalAuditEvent.query.filter(
            JournalAuditEvent.company_id == company_a.id,
            JournalAuditEvent.journal_entry_id.in_(
                [original.id, reversal.id]
            ),
        ).all()
        record(
            "Valid reversal posts and marks original reversed",
            reversed_original.status == "reversed"
            and posted_reversal.status == "posted"
            and any(
                event.event_type == "reversed"
                and event.performed_by_id == actor_a.id
                for event in reversal_audits
            )
            and any(
                event.event_type == "posted"
                and event.performed_by_id == actor_a.id
                for event in reversal_audits
            ),
            f"original={reversed_original.status}; reversal={posted_reversal.status}",
        )

        # 6. Company isolation: actor, account, journal.
        foreign_actor_ok, foreign_actor_details = expect_error(
            lambda: create_journal(
                company_id=company_a.id,
                actor_id=actor_b.id,
                journal_number="JT-FOREIGN-ACTOR",
                journal_date=date(2026, 1, 15),
                description="Foreign actor test",
                currency="ZAR",
                lines=journal_lines(debit_a, credit_a),
                accounting_period_id=period_a.id,
            )
        )
        record(
            "Foreign company actor cannot create a journal",
            foreign_actor_ok,
            foreign_actor_details,
        )

        foreign_account_ok, foreign_account_details = expect_error(
            lambda: create_journal(
                company_id=company_a.id,
                actor_id=actor_a.id,
                journal_number="JT-FOREIGN-ACCOUNT",
                journal_date=date(2026, 1, 15),
                description="Foreign account test",
                currency="ZAR",
                lines=journal_lines(debit_b, credit_a),
                accounting_period_id=period_a.id,
            )
        )
        record(
            "Foreign company account cannot be used in a journal",
            foreign_account_ok,
            foreign_account_details,
        )

        foreign_journal = create_journal(
            company_id=company_b.id,
            actor_id=actor_b.id,
            journal_number="JB-001",
            journal_date=date(2026, 1, 15),
            description="Company B journal",
            currency="ZAR",
            lines=journal_lines(debit_b, credit_b),
            accounting_period_id=periods_b[0].id,
        )
        db.session.flush()

        foreign_journal_ok, foreign_journal_details = expect_error(
            lambda: update_journal(
                company_id=company_a.id,
                journal_id=foreign_journal.id,
                actor_id=actor_a.id,
                lines=journal_lines(debit_a, credit_a),
                expected_snapshot=journal_draft_snapshot(foreign_journal),
            )
        )
        record(
            "Company A cannot update Company B journal",
            foreign_journal_ok,
            foreign_journal_details,
        )

        # 7. Audit event integrity: attribution and event history.
        original_audits = JournalAuditEvent.query.filter_by(
            company_id=company_a.id,
            journal_entry_id=original.id,
        ).all()
        event_types = {event.event_type for event in original_audits}
        all_attributed = all(
            event.performed_by_id == actor_a.id
            for event in original_audits
        )
        record(
            "Original journal audit history retains actor attribution",
            {"created", "posted", "reversed"}.issubset(event_types)
            and all_attributed,
            f"events={sorted(event_types)}; attributed={all_attributed}",
        )

        # Preserve all completed test fixtures before testing caller rollback.
        # This commit is confined to the disposable SQLite test database.
        db.session.commit()

        # 8. Caller-owned transaction rollback.
        before_count = JournalEntry.query.filter_by(
            company_id=company_a.id
        ).count()
        rollback_draft = create_a_draft("JT-ROLLBACK")
        rollback_id = rollback_draft.id
        db.session.flush()
        db.session.rollback()
        after_count = JournalEntry.query.filter_by(
            company_id=company_a.id
        ).count()
        record(
            "Caller rollback removes uncommitted journal creation",
            after_count == before_count
            and db.session.get(JournalEntry, rollback_id) is None,
            f"before={before_count}; after={after_count}",
        )

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
    print("JOURNAL SERVICE TEST SUMMARY")
    print("=" * 55)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {len(results)}")

    if failed or script_error:
        print("RESULT: FAILED — review failures or script error.")
    else:
        print("RESULT: PASSED — all journal service checks completed.")

    print("SQLite tests do not verify PostgreSQL row-lock concurrency.")

if failed or script_error:
    raise SystemExit(1)
