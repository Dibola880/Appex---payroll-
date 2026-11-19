"""Database-independent preparation and lifecycle safeguards for journals."""

from datetime import datetime

from app.journal_validation import (
    validate_journal,
    JournalValidationError,
)


class JournalLifecycleError(ValueError):
    """Raised when a journal lifecycle operation is not permitted."""


def _positive_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise JournalLifecycleError(
            f"{field} must be a positive integer."
        )
    return value


def _plain_dict(value, field):
    if not isinstance(value, dict):
        raise JournalLifecycleError(
            f"{field} must be a plain dictionary."
        )
    return value


def prepare_draft_journal(
    company_id,
    journal_number,
    created_by_id,
    creator_company_id,
    journal_date,
    description,
    currency,
    lines,
    accounts,
    source_type="manual",
    source_id=None,
):
    """Prepare normalized draft data without database access."""

    company_id = _positive_id(company_id, "company_id")
    created_by_id = _positive_id(created_by_id, "created_by_id")
    creator_company_id = _positive_id(
        creator_company_id,
        "creator_company_id",
    )

    if creator_company_id != company_id:
        raise JournalLifecycleError(
            "The journal creator must belong to the journal company."
        )

    if not isinstance(journal_number, str):
        raise JournalLifecycleError("journal_number must be text.")

    journal_number = journal_number.strip()

    if not journal_number or len(journal_number) > 40:
        raise JournalLifecycleError(
            "journal_number must contain between 1 and 40 characters."
        )

    validated = validate_journal(
        company_id=company_id,
        journal_date=journal_date,
        description=description,
        currency=currency,
        lines=lines,
        accounts=accounts,
        source_type=source_type,
        source_id=source_id,
    )

    return {
        "header": {
            "company_id": company_id,
            "journal_number": journal_number,
            "journal_date": validated["journal_date"],
            "description": validated["description"],
            "currency": validated["currency"],
            "source_type": validated["source_type"],
            "source_id": validated["source_id"],
            "status": "draft",
            "created_by_id": created_by_id,
            "posted_by_id": None,
            "posted_at": None,
            "reversal_of_id": None,
        },
        "lines": validated["lines"],
        "total_debit": validated["total_debit"],
        "total_credit": validated["total_credit"],
    }


def assert_journal_editable(journal):
    """Only draft journals may be edited or deleted."""

    journal = _plain_dict(journal, "journal")

    if journal.get("status") != "draft":
        raise JournalLifecycleError(
            "Only draft journals may be edited or deleted."
        )

    return True


def prepare_posting_transition(
    journal,
    actor_company_id,
    actor_id,
    posted_at,
):
    """Prepare posting metadata without changing or persisting a journal."""

    journal = _plain_dict(journal, "journal")

    company_id = _positive_id(
        journal.get("company_id"),
        "journal company_id",
    )
    actor_company_id = _positive_id(
        actor_company_id,
        "actor_company_id",
    )
    actor_id = _positive_id(actor_id, "actor_id")
    _positive_id(journal.get("id"), "journal id")

    if journal.get("status") != "draft":
        raise JournalLifecycleError(
            "Only draft journals may be posted."
        )

    if actor_company_id != company_id:
        raise JournalLifecycleError(
            "The posting user must belong to the journal company."
        )

    if not isinstance(posted_at, datetime):
        raise JournalLifecycleError(
            "posted_at must be a datetime value."
        )

    if journal.get("posted_by_id") is not None:
        raise JournalLifecycleError(
            "A draft journal cannot already have a posting user."
        )

    if journal.get("posted_at") is not None:
        raise JournalLifecycleError(
            "A draft journal cannot already have a posting timestamp."
        )

    return {
        "status": "posted",
        "posted_by_id": actor_id,
        "posted_at": posted_at,
    }


def prepare_reversal_draft(
    original_journal,
    original_lines,
    reversal_journal_number,
    reversal_date,
    created_by_id,
    creator_company_id,
    accounts,
    existing_reversal_of_ids=(),
    description=None,
):
    """Prepare a new draft that reverses a posted journal without mutation."""

    original_journal = _plain_dict(
        original_journal,
        "original_journal",
    )

    original_id = _positive_id(
        original_journal.get("id"),
        "original journal id",
    )
    company_id = _positive_id(
        original_journal.get("company_id"),
        "original journal company_id",
    )

    if original_journal.get("status") != "posted":
        raise JournalLifecycleError(
            "Only a posted journal may be reversed."
        )

    if original_journal.get("reversal_of_id") is not None:
        raise JournalLifecycleError(
            "A reversal journal cannot itself be reversed."
        )

    if not isinstance(existing_reversal_of_ids, (list, tuple, set, frozenset)):
        raise JournalLifecycleError(
            "existing_reversal_of_ids must be a collection of journal IDs."
        )

    existing_ids = {
        _positive_id(value, "existing reversal journal reference")
        for value in existing_reversal_of_ids
    }

    if original_id in existing_ids:
        raise JournalLifecycleError(
            "This journal already has a reversal."
        )

    if not isinstance(original_lines, (list, tuple)):
        raise JournalLifecycleError(
            "original_lines must be a list or tuple."
        )

    if not original_lines:
        raise JournalLifecycleError(
            "The original journal has no lines to reverse."
        )

    reversed_lines = []

    for line_number, original_line in enumerate(original_lines, start=1):
        original_line = _plain_dict(
            original_line,
            "original journal line",
        )

        account_id = _positive_id(
            original_line.get("account_id"),
            "original line account_id",
        )

        if "debit" not in original_line or "credit" not in original_line:
            raise JournalLifecycleError(
                "Every original journal line must contain debit and credit amounts."
            )

        reversed_lines.append({
            "line_number": line_number,
            "account_id": account_id,
            "description": original_line.get("description") or "",
            "debit": original_line["credit"],
            "credit": original_line["debit"],
        })

    if description is None:
        original_number = original_journal.get("journal_number", original_id)
        original_description = original_journal.get("description", "")
        description = (
            f"Reversal of {original_number}: {original_description}"
        ).strip()

    if not isinstance(description, str):
        raise JournalLifecycleError(
            "Reversal description must be text."
        )

    try:
        reversal = prepare_draft_journal(
            company_id=company_id,
            journal_number=reversal_journal_number,
            created_by_id=created_by_id,
            creator_company_id=creator_company_id,
            journal_date=reversal_date,
            description=description,
            currency=original_journal.get("currency"),
            lines=reversed_lines,
            accounts=accounts,
            source_type="reversal",
            source_id=original_id,
        )
    except JournalValidationError as exc:
        raise JournalLifecycleError(str(exc)) from exc

    reversal["header"]["reversal_of_id"] = original_id

    return reversal


def prepare_reversal_posting_transitions(
    original_journal,
    reversal_journal,
    actor_company_id,
    actor_id,
    posted_at,
):
    """Prepare both sides of a reversal posting without mutating either journal."""

    original_journal = _plain_dict(
        original_journal,
        "original_journal",
    )
    reversal_journal = _plain_dict(
        reversal_journal,
        "reversal_journal",
    )

    original_id = _positive_id(
        original_journal.get("id"),
        "original journal id",
    )
    company_id = _positive_id(
        original_journal.get("company_id"),
        "original journal company_id",
    )
    reversal_id = _positive_id(
        reversal_journal.get("id"),
        "reversal journal id",
    )
    reversal_company_id = _positive_id(
        reversal_journal.get("company_id"),
        "reversal journal company_id",
    )

    if original_id == reversal_id:
        raise JournalLifecycleError(
            "A journal cannot reverse itself."
        )

    if company_id != reversal_company_id:
        raise JournalLifecycleError(
            "The original and reversal journals must belong to the same company."
        )

    if original_journal.get("status") != "posted":
        raise JournalLifecycleError(
            "Only a posted original journal can be reversed."
        )

    if original_journal.get("reversal_of_id") is not None:
        raise JournalLifecycleError(
            "A reversal journal cannot be used as the original journal."
        )

    if reversal_journal.get("status") != "draft":
        raise JournalLifecycleError(
            "The reversal journal must still be a draft."
        )

    if reversal_journal.get("reversal_of_id") != original_id:
        raise JournalLifecycleError(
            "The reversal journal must reference the original journal."
        )

    if reversal_journal.get("source_type") != "reversal":
        raise JournalLifecycleError(
            "The reversal journal must have source_type 'reversal'."
        )

    if reversal_journal.get("source_id") != original_id:
        raise JournalLifecycleError(
            "The reversal journal source must reference the original journal."
        )

    reversal_transition = prepare_posting_transition(
        journal=reversal_journal,
        actor_company_id=actor_company_id,
        actor_id=actor_id,
        posted_at=posted_at,
    )

    original_transition = {
        "status": "reversed",
    }

    return {
        "original_journal_id": original_id,
        "reversal_journal_id": reversal_id,
        "original_transition": original_transition,
        "reversal_transition": reversal_transition,
    }

def prepare_period_aware_posting_transition(
    journal,
    actor_company_id,
    actor_id,
    posted_at,
    financial_years,
    periods,
):
    """Prepare posting metadata and assign the journal's eligible period."""

    from app.accounting_period_validation import (
        assert_journal_date_postable,
        AccountingPeriodValidationError,
    )

    journal = _plain_dict(journal, "journal")

    try:
        period_result = assert_journal_date_postable(
            company_id=journal.get("company_id"),
            journal_date=journal.get("journal_date"),
            financial_years=financial_years,
            periods=periods,
        )
    except AccountingPeriodValidationError as exc:
        raise JournalLifecycleError(str(exc)) from exc

    validated_period_id = period_result["accounting_period_id"]
    stored_period_id = _positive_id(
        journal.get("accounting_period_id"),
        "journal.accounting_period_id",
    )
    if stored_period_id != validated_period_id:
        raise JournalLifecycleError(
            "The draft accounting period does not match its journal date."
        )

    transition = prepare_posting_transition(
        journal=journal,
        actor_company_id=actor_company_id,
        actor_id=actor_id,
        posted_at=posted_at,
    )

    transition["accounting_period_id"] = (
        period_result["accounting_period_id"]
    )

    return transition

def prepare_period_aware_reversal_posting_transitions(
    original_journal,
    reversal_journal,
    actor_company_id,
    actor_id,
    posted_at,
    financial_years,
    periods,
):
    """Prepare a reversal and assign its own eligible accounting period."""

    from app.accounting_period_validation import (
        assert_journal_date_postable,
        AccountingPeriodValidationError,
    )

    original_journal = _plain_dict(
        original_journal, "original_journal"
    )
    reversal_journal = _plain_dict(
        reversal_journal, "reversal_journal"
    )

    _positive_id(
        original_journal.get("accounting_period_id"),
        "original accounting_period_id",
    )

    stored_period_id = reversal_journal.get("accounting_period_id")
    if stored_period_id is not None:
        stored_period_id = _positive_id(
            stored_period_id,
            "reversal accounting_period_id",
        )

    try:
        period_result = assert_journal_date_postable(
            company_id=reversal_journal.get("company_id"),
            journal_date=reversal_journal.get("journal_date"),
            financial_years=financial_years,
            periods=periods,
        )
    except AccountingPeriodValidationError as exc:
        raise JournalLifecycleError(str(exc)) from exc

    validated_period_id = period_result["accounting_period_id"]
    if (
        stored_period_id is not None
        and stored_period_id != validated_period_id
    ):
        raise JournalLifecycleError(
            "Reversal draft accounting period does not match its date."
        )

    transitions = prepare_reversal_posting_transitions(
        original_journal=original_journal,
        reversal_journal=reversal_journal,
        actor_company_id=actor_company_id,
        actor_id=actor_id,
        posted_at=posted_at,
    )

    transitions["reversal_transition"]["accounting_period_id"] = (
        validated_period_id
    )

    return transitions
