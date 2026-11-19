"""Database-backed journal lifecycle and persistence operations.

Transaction ownership remains with the caller. These functions flush but
never commit or silently roll back.

Posting lock order:
    financial year -> accounting periods -> journals (ascending ID)
    -> accounts (ascending ID).

PostgreSQL row locks provide the intended concurrency protection.
SQLite does not provide equivalent row-level locking.
"""

from datetime import date, datetime
from decimal import Decimal


from . import db
from .accounting_period_validation import (
    AccountingPeriodValidationError,
    assert_journal_date_postable,
)
from .models import (
    Account,
    AccountingPeriod,
    FinancialYear,
    JournalEntry,
    JournalLine,
    JournalAuditEvent,
    User,
)
from .journal_lifecycle import (
    JournalLifecycleError,
    assert_journal_editable,
    prepare_draft_journal,
    prepare_period_aware_posting_transition,
    prepare_reversal_draft,
    prepare_period_aware_reversal_posting_transitions,
)
from .journal_validation import (
    JournalValidationError,
    validate_journal,
)


class JournalServiceError(ValueError):
    """Raised when a journal persistence operation is invalid."""


class JournalDraftConflict(JournalServiceError):
    """Raised when a draft changed after its edit form was opened."""


def _fail(message):
    raise JournalServiceError(message)


def _now(value=None):
    value = value or datetime.utcnow()
    if not isinstance(value, datetime):
        _fail("Timestamp must be a datetime value.")
    return value


def _actor(company_id, actor_id):
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        _fail("company_id must be a positive integer.")

    if (
        isinstance(actor_id, bool)
        or not isinstance(actor_id, int)
        or actor_id <= 0
    ):
        _fail("actor_id must be a positive integer.")

    user = User.query.filter_by(
        id=actor_id,
        company_id=company_id,
    ).first()

    if user is None:
        _fail("The acting user does not belong to this company.")

    return user


def _journal(company_id, journal_id, lock=True):
    query = JournalEntry.query.filter_by(
        id=journal_id,
        company_id=company_id,
    )

    if lock:
        query = query.with_for_update().populate_existing()

    result = query.first()

    if result is None:
        _fail("Journal not found.")

    return result


def _assert_journal_number_available(
    company_id,
    journal_number,
    exclude_journal_id=None,
):
    query = JournalEntry.query.filter_by(
        company_id=company_id,
        journal_number=journal_number,
    )

    if exclude_journal_id is not None:
        query = query.filter(JournalEntry.id != exclude_journal_id)

    if query.first() is not None:
        _fail("This journal number is already in use by this company.")


def _journal_dict(journal):
    return {
        "id": journal.id,
        "company_id": journal.company_id,
        "journal_number": journal.journal_number,
        "journal_date": journal.journal_date,
        "accounting_period_id": journal.accounting_period_id,
        "description": journal.description,
        "currency": journal.currency,
        "source_type": journal.source_type,
        "source_id": journal.source_id,
        "status": journal.status,
        "created_by_id": journal.created_by_id,
        "posted_by_id": journal.posted_by_id,
        "posted_at": journal.posted_at,
        "reversal_of_id": journal.reversal_of_id,
    }


def _line_dict(line):
    return {
        "line_number": line.line_number,
        "account_id": line.account_id,
        "description": line.description,
        "debit": Decimal(line.debit),
        "credit": Decimal(line.credit),
    }


def _lines(company_id, journal_id):
    return [
        _line_dict(line)
        for line in JournalLine.query.filter_by(
            company_id=company_id,
            journal_entry_id=journal_id,
        ).order_by(JournalLine.line_number).populate_existing().all()
    ]


def journal_draft_snapshot(journal):
    """Build a JSON-safe snapshot of a journal header and its ordered lines."""
    return {
        "company_id": journal.company_id,
        "journal_id": journal.id,
        "journal_number": journal.journal_number,
        "journal_date": journal.journal_date.isoformat(),
        "accounting_period_id": journal.accounting_period_id,
        "description": journal.description,
        "currency": journal.currency,
        "source_type": journal.source_type,
        "source_id": journal.source_id,
        "status": journal.status,
        "created_by_id": journal.created_by_id,
        "posted_by_id": journal.posted_by_id,
        "posted_at": (
            journal.posted_at.isoformat()
            if journal.posted_at is not None else None
        ),
        "reversal_of_id": journal.reversal_of_id,
        "lines": [
            {
                "line_number": line["line_number"],
                "account_id": line["account_id"],
                "description": line["description"],
                "debit": str(line["debit"]),
                "credit": str(line["credit"]),
            }
            for line in _lines(journal.company_id, journal.id)
        ],
    }


def _locked_accounts(company_id):
    """Load and lock the company's chart for authoritative validation."""
    rows = (
        Account.query
        .filter_by(company_id=company_id)
        .order_by(Account.id)
        .with_for_update()
        .populate_existing()
        .all()
    )

    return {
        row.id: {
            "id": row.id,
            "company_id": row.company_id,
            "parent_id": row.parent_id,
            "is_active": row.is_active,
            "allow_manual_posting": row.allow_manual_posting,
        }
        for row in rows
    }


def _validate_data(
    company_id,
    journal_date,
    description,
    currency,
    source_type,
    source_id,
    lines,
    accounts,
):
    return validate_journal(
        company_id=company_id,
        journal_date=journal_date,
        description=description,
        currency=currency,
        source_type=source_type,
        source_id=source_id,
        lines=lines,
        accounts=accounts,
    )


def _replace_lines(journal, lines):
    existing = JournalLine.query.filter_by(
        company_id=journal.company_id,
        journal_entry_id=journal.id,
    ).all()

    for line in existing:
        db.session.delete(line)

    # Flush deletions before reusing the existing journal line numbers.
    # This remains inside the caller-owned transaction and is rollback-safe.
    db.session.flush()

    for item in lines:
        db.session.add(
            JournalLine(
                company_id=journal.company_id,
                journal_entry_id=journal.id,
                line_number=item["line_number"],
                account_id=item["account_id"],
                description=item["description"],
                debit=item["debit"],
                credit=item["credit"],
            )
        )


def _write_audit(
    journal,
    actor_id,
    event_type,
    reason=None,
    details=None,
    performed_at=None,
):
    if reason is not None:
        if not isinstance(reason, str):
            _fail("Audit reason must be text or None.")
        reason = reason.strip() or None
        if reason is not None and len(reason) > 500:
            _fail("Audit reason cannot exceed 500 characters.")

    event = JournalAuditEvent(
        company_id=journal.company_id,
        journal_entry_id=journal.id,
        event_type=event_type,
        performed_by_id=actor_id,
        performed_at=_now(performed_at),
        reason=reason,
        details=details,
    )

    db.session.add(event)
    return event


def _persist_draft(company_id, prepared, accounting_period_id=None):
    header = prepared["header"]

    journal = JournalEntry(
        company_id=company_id,
        journal_number=header["journal_number"],
        journal_date=header["journal_date"],
        description=header["description"],
        currency=header["currency"],
        source_type=header["source_type"],
        source_id=header["source_id"],
        status="draft",
        created_by_id=header["created_by_id"],
        posted_by_id=None,
        posted_at=None,
        reversal_of_id=header.get("reversal_of_id"),
        accounting_period_id=accounting_period_id,
    )

    db.session.add(journal)
    db.session.flush()

    _replace_lines(journal, prepared["lines"])
    db.session.flush()

    return journal


def _period_context(company_id, journal_date):
    """Lock the applicable year and its periods before journal rows."""
    years = (
        FinancialYear.query
        .filter_by(company_id=company_id)
        .order_by(FinancialYear.id)
        .all()
    )

    candidates = [
        year for year in years
        if year.start_date <= journal_date <= year.end_date
    ]

    if len(candidates) != 1:
        _fail(
            "Journal date must belong to exactly one financial year."
        )

    year_id = candidates[0].id

    year = (
        FinancialYear.query
        .filter_by(id=year_id, company_id=company_id)
        .with_for_update()
        .populate_existing()
        .first()
    )

    if year is None:
        _fail("Financial year not found.")

    periods = (
        AccountingPeriod.query
        .filter_by(
            company_id=company_id,
            financial_year_id=year.id,
        )
        .order_by(AccountingPeriod.id)
        .with_for_update()
        .populate_existing()
        .all()
    )

    # Refresh all year data used by the pure validator.
    years = (
        FinancialYear.query
        .filter_by(company_id=company_id)
        .order_by(FinancialYear.id)
        .all()
    )

    year_data = [
        {
            "id": item.id,
            "company_id": item.company_id,
            "start_date": item.start_date,
            "end_date": item.end_date,
            "status": item.status,
        }
        for item in years
    ]

    period_data = [
        {
            "id": item.id,
            "company_id": item.company_id,
            "financial_year_id": item.financial_year_id,
            "start_date": item.start_date,
            "end_date": item.end_date,
            "status": item.status,
        }
        for item in periods
    ]

    return year_data, period_data


def _lock_journals(company_id, journal_ids):
    ids = sorted(set(journal_ids))

    rows = (
        JournalEntry.query
        .filter(
            JournalEntry.company_id == company_id,
            JournalEntry.id.in_(ids),
        )
        .order_by(JournalEntry.id)
        .with_for_update()
        .populate_existing()
        .all()
    )

    if len(rows) != len(ids):
        _fail("One or more journals could not be found.")

    return {row.id: row for row in rows}


def _audit_details(prepared):
    return {
        "journal_number": prepared["header"]["journal_number"],
        "journal_date": prepared["header"]["journal_date"].isoformat(),
        "currency": prepared["header"]["currency"],
        "line_count": len(prepared["lines"]),
        "total_debit": str(prepared["total_debit"]),
        "total_credit": str(prepared["total_credit"]),
    }


def create_journal(
    company_id,
    actor_id,
    journal_number,
    journal_date,
    description,
    currency,
    lines,
    source_type="manual",
    source_id=None,
    now=None,
    accounting_period_id=None,
):
    """Validate and persist a new draft journal in an open period."""
    _actor(company_id, actor_id)

    if (
        not isinstance(journal_date, date)
        or isinstance(journal_date, datetime)
    ):
        raise JournalServiceError(
            "Journal date must be a date, not a datetime."
        )

    # Lock financial year and accounting periods before accounts.
    year_data, period_data = _period_context(
        company_id,
        journal_date,
    )

    try:
        period_context = assert_journal_date_postable(
            company_id,
            journal_date,
            year_data,
            period_data,
        )
    except AccountingPeriodValidationError as exc:
        raise JournalServiceError(str(exc)) from exc

    validated_period_id = period_context["accounting_period_id"]

    if accounting_period_id is not None:
        if (
            isinstance(accounting_period_id, bool)
            or not isinstance(accounting_period_id, int)
            or accounting_period_id <= 0
        ):
            raise JournalServiceError(
                "Select a valid accounting period."
            )

        if accounting_period_id != validated_period_id:
            raise JournalServiceError(
                "The selected accounting period does not cover "
                "the journal date."
            )

    accounts = _locked_accounts(company_id)

    try:
        prepared = prepare_draft_journal(
            company_id=company_id,
            journal_number=journal_number,
            created_by_id=actor_id,
            creator_company_id=company_id,
            journal_date=journal_date,
            description=description,
            currency=currency,
            lines=lines,
            accounts=accounts,
            source_type=source_type,
            source_id=source_id,
        )
    except (JournalLifecycleError, JournalValidationError) as exc:
        raise JournalServiceError(str(exc)) from exc

    _assert_journal_number_available(
        company_id,
        prepared["header"]["journal_number"],
    )

    journal = _persist_draft(
        company_id,
        prepared,
        validated_period_id,
    )

    _write_audit(
        journal,
        actor_id,
        "created",
        details=_audit_details(prepared),
        performed_at=now,
    )

    db.session.flush()
    return journal
def update_journal(
    company_id,
    journal_id,
    actor_id,
    lines,
    journal_date=None,
    description=None,
    currency=None,
    journal_number=None,
    reason=None,
    now=None,
    accounting_period_id=None,
    expected_snapshot=None,
):
    """Update a draft only when its original snapshot is still current."""
    _actor(company_id, actor_id)

    # Read without locking to determine which accounting calendar to lock.
    initial = _journal(company_id, journal_id, lock=False)
    target_date = (
        journal_date if journal_date is not None else initial.journal_date
    )

    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        _fail("Journal date must be a valid calendar date.")

    # Preserve the posting workflow lock order:
    # financial year -> accounting periods -> journal -> accounts.
    year_data, period_data = _period_context(company_id, target_date)
    try:
        period_context = assert_journal_date_postable(
            company_id,
            target_date,
            year_data,
            period_data,
        )
    except AccountingPeriodValidationError as exc:
        raise JournalServiceError(str(exc)) from exc

    validated_period_id = period_context["accounting_period_id"]

    if accounting_period_id is not None:
        if (
            isinstance(accounting_period_id, bool)
            or not isinstance(accounting_period_id, int)
            or accounting_period_id <= 0
        ):
            _fail("Accounting period selection is invalid.")
        if accounting_period_id != validated_period_id:
            _fail("Selected accounting period does not match the journal date.")

    # Lock and refresh only after the target calendar locks are held.
    journal = _journal(company_id, journal_id, lock=True)

    # Compare the signed original state after obtaining the journal lock.
    if expected_snapshot is None:
        raise JournalDraftConflict(
            "The original edit snapshot is missing. Reload the current draft."
        )

    if journal_draft_snapshot(journal) != expected_snapshot:
        raise JournalDraftConflict(
            "This journal changed after you opened it. "
            "Reload the current draft before editing it again."
        )

    if (
        journal.reversal_of_id is not None
        or journal.source_type == "reversal"
    ):
        _fail("Reversal drafts cannot be edited.")

    try:
        assert_journal_editable(_journal_dict(journal))
    except JournalLifecycleError as exc:
        raise JournalServiceError(str(exc)) from exc

    accounts = _locked_accounts(company_id)

    try:
        prepared = prepare_draft_journal(
            company_id=company_id,
            journal_number=(
                journal_number
                if journal_number is not None
                else journal.journal_number
            ),
            created_by_id=journal.created_by_id,
            creator_company_id=company_id,
            journal_date=target_date,
            description=(
                description if description is not None else journal.description
            ),
            currency=currency if currency is not None else journal.currency,
            lines=lines,
            accounts=accounts,
            source_type=journal.source_type,
            source_id=journal.source_id,
        )
    except (JournalLifecycleError, JournalValidationError) as exc:
        raise JournalServiceError(str(exc)) from exc

    _assert_journal_number_available(
        company_id,
        prepared["header"]["journal_number"],
        exclude_journal_id=journal.id,
    )

    old_number = journal.journal_number
    old_period_id = journal.accounting_period_id
    header = prepared["header"]

    journal.journal_number = header["journal_number"]
    journal.journal_date = header["journal_date"]
    journal.accounting_period_id = validated_period_id
    journal.description = header["description"]
    journal.currency = header["currency"]

    _replace_lines(journal, prepared["lines"])
    db.session.flush()

    _write_audit(
        journal,
        actor_id,
        "updated",
        reason=reason,
        details={
            "previous_journal_number": old_number,
            "journal_number": journal.journal_number,
            "previous_accounting_period_id": old_period_id,
            "accounting_period_id": journal.accounting_period_id,
            "line_count": len(prepared["lines"]),
            "total_debit": str(prepared["total_debit"]),
            "total_credit": str(prepared["total_credit"]),
        },
        performed_at=now,
    )
    db.session.flush()
    return journal

def post_journal(
    company_id,
    journal_id,
    actor_id,
    now=None,
):
    """Post a draft after rechecking its lines, accounts and period."""
    actor = _actor(company_id, actor_id)

    # Read only to discover the period-lock target.
    initial = _journal(company_id, journal_id, lock=False)
    year_data, period_data = _period_context(
        company_id,
        initial.journal_date,
    )

    # The period locks are held before the journal lock.
    journal = _journal(company_id, journal_id, lock=True)

    if journal.journal_date != initial.journal_date:
        _fail(
            "Journal date changed while preparing posting; "
            "retry the operation."
        )

    if journal.status != "draft":
        _fail("Only draft journals may be posted.")

    if (
        journal.reversal_of_id is not None
        or journal.source_type == "reversal"
    ):
        _fail(
            "Reversal journals must be posted through post_reversal()."
        )

    accounts = _locked_accounts(company_id)
    lines = _lines(company_id, journal.id)

    try:
        validated = _validate_data(
            company_id=company_id,
            journal_date=journal.journal_date,
            description=journal.description,
            currency=journal.currency,
            source_type=journal.source_type,
            source_id=journal.source_id,
            lines=lines,
            accounts=accounts,
        )

        transition = prepare_period_aware_posting_transition(
            journal=_journal_dict(journal),
            actor_company_id=actor.company_id,
            actor_id=actor.id,
            posted_at=_now(now),
            financial_years=year_data,
            periods=period_data,
        )
    except (JournalLifecycleError, JournalValidationError) as exc:
        raise JournalServiceError(str(exc)) from exc

    journal.status = transition["status"]
    journal.posted_by_id = transition["posted_by_id"]
    journal.posted_at = transition["posted_at"]
    journal.accounting_period_id = transition["accounting_period_id"]

    _write_audit(
        journal,
        actor_id,
        "posted",
        details={
            "accounting_period_id": journal.accounting_period_id,
            "total_debit": str(validated["total_debit"]),
            "total_credit": str(validated["total_credit"]),
            "currency": journal.currency,
        },
        performed_at=now,
    )

    db.session.flush()
    return journal


def create_reversal(
    company_id,
    original_journal_id,
    actor_id,
    reversal_journal_number,
    reversal_date,
    reason,
    description=None,
    now=None,
):
    """Create a draft reversal in its date's eligible open period."""
    _actor(company_id, actor_id)

    if (
        not isinstance(reversal_date, date)
        or isinstance(reversal_date, datetime)
    ):
        raise JournalServiceError(
            "Reversal date must be a date, not a datetime."
        )

    # Preserve the established lock order: calendar -> journal -> accounts.
    year_data, period_data = _period_context(
        company_id,
        reversal_date,
    )

    try:
        period_context = assert_journal_date_postable(
            company_id,
            reversal_date,
            year_data,
            period_data,
        )
    except AccountingPeriodValidationError as exc:
        raise JournalServiceError(str(exc)) from exc

    validated_period_id = period_context["accounting_period_id"]

    # Lock the original before checking for an existing reversal. This
    # serializes concurrent reversal creation attempts for the same journal.
    original = _journal(company_id, original_journal_id)

    if original.status != "posted":
        _fail("Only a posted journal may be reversed.")

    existing = JournalEntry.query.filter_by(
        company_id=company_id,
        reversal_of_id=original.id,
    ).first()

    if existing is not None:
        _fail("This journal already has a reversal.")

    accounts = _locked_accounts(company_id)
    original_lines = _lines(company_id, original.id)

    try:
        prepared = prepare_reversal_draft(
            original_journal=_journal_dict(original),
            original_lines=original_lines,
            reversal_journal_number=reversal_journal_number,
            reversal_date=reversal_date,
            created_by_id=actor_id,
            creator_company_id=company_id,
            accounts=accounts,
            existing_reversal_of_ids=(),
            description=description,
        )
    except (JournalLifecycleError, JournalValidationError) as exc:
        raise JournalServiceError(str(exc)) from exc

    journal = _persist_draft(
        company_id,
        prepared,
        validated_period_id,
    )
    journal.reversal_of_id = original.id
    db.session.flush()

    _write_audit(
        journal,
        actor_id,
        "created",
        reason=reason,
        details={
            "reversal_of_id": original.id,
            "original_journal_number": original.journal_number,
            "currency": original.currency,
        },
        performed_at=now,
    )

    db.session.flush()
    return journal


def _assert_reversal_lines_match(original_lines, reversal_lines):
    if len(original_lines) != len(reversal_lines):
        _fail("Reversal lines do not match the original journal.")

    for line_number, (original_line, reversal_line) in enumerate(
        zip(original_lines, reversal_lines),
        start=1,
    ):
        expected = {
            "line_number": line_number,
            "account_id": original_line["account_id"],
            "description": original_line.get("description") or "",
            "debit": original_line["credit"],
            "credit": original_line["debit"],
        }

        if reversal_line != expected:
            _fail(
                "Reversal lines must exactly mirror the original journal."
            )


def post_reversal(
    company_id,
    original_journal_id,
    reversal_journal_id,
    actor_id,
    reason,
    now=None,
):
    """Post a reversal and mark its original reversed atomically."""
    actor = _actor(company_id, actor_id)

    # Discover the reversal date before taking period locks.
    initial_reversal = _journal(
        company_id,
        reversal_journal_id,
        lock=False,
    )

    year_data, period_data = _period_context(
        company_id,
        initial_reversal.journal_date,
    )

    # Lock both journal rows in ascending ID order.
    locked = _lock_journals(
        company_id,
        [original_journal_id, reversal_journal_id],
    )

    original = locked[original_journal_id]
    reversal = locked[reversal_journal_id]

    if reversal.journal_date != initial_reversal.journal_date:
        _fail(
            "Reversal date changed while preparing posting; "
            "retry the operation."
        )

    if original.status != "posted":
        _fail("Only a posted journal may be reversed.")

    if reversal.status != "draft":
        _fail("Only a draft reversal may be posted.")

    if reversal.reversal_of_id != original.id:
        _fail("The reversal does not reference the supplied original.")

    if (
        reversal.source_type != "reversal"
        or reversal.source_id != original.id
    ):
        _fail("Reversal source metadata does not match the original journal.")

    if original.currency != reversal.currency:
        _fail("A reversal must use the original journal currency.")

    accounts = _locked_accounts(company_id)
    original_lines = _lines(company_id, original.id)
    reversal_lines = _lines(company_id, reversal.id)

    _assert_reversal_lines_match(original_lines, reversal_lines)

    # Revalidate the reversal's actual persisted lines and accounts.
    try:
        validated = _validate_data(
            company_id=company_id,
            journal_date=reversal.journal_date,
            description=reversal.description,
            currency=reversal.currency,
            source_type=reversal.source_type,
            source_id=reversal.source_id,
            lines=reversal_lines,
            accounts=accounts,
        )
    except JournalValidationError as exc:
        raise JournalServiceError(str(exc)) from exc

    try:
        transitions = prepare_period_aware_reversal_posting_transitions(
            original_journal=_journal_dict(original),
            reversal_journal=_journal_dict(reversal),
            actor_company_id=actor.company_id,
            actor_id=actor.id,
            posted_at=_now(now),
            financial_years=year_data,
            periods=period_data,
        )
    except JournalLifecycleError as exc:
        raise JournalServiceError(str(exc)) from exc

    original_transition = transitions["original_transition"]
    reversal_transition = transitions["reversal_transition"]

    original.status = original_transition["status"]

    reversal.status = reversal_transition["status"]
    reversal.posted_by_id = reversal_transition["posted_by_id"]
    reversal.posted_at = reversal_transition["posted_at"]
    reversal.accounting_period_id = (
        reversal_transition["accounting_period_id"]
    )

    _write_audit(
        original,
        actor_id,
        "reversed",
        reason=reason,
        details={
            "reversal_journal_id": reversal.id,
            "reversal_journal_number": reversal.journal_number,
        },
        performed_at=now,
    )

    _write_audit(
        reversal,
        actor_id,
        "posted",
        reason=reason,
        details={
            "original_journal_id": original.id,
            "accounting_period_id": reversal.accounting_period_id,
            "total_debit": str(validated["total_debit"]),
            "total_credit": str(validated["total_credit"]),
            "currency": reversal.currency,
        },
        performed_at=now,
    )

    db.session.flush()
    return original, reversal
