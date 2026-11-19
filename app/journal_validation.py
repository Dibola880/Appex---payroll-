"""Pure validation for company-owned double-entry journals."""

from datetime import date
from decimal import Decimal, InvalidOperation


MAX_AMOUNT = Decimal("999999999999.99")
ZERO = Decimal("0.00")


class JournalValidationError(ValueError):
    """Raised when journal input violates accounting rules."""


def _positive_company_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise JournalValidationError(
            f"{field} must be a positive integer."
        )
    return value


def _decimal_amount(value, field):
    if isinstance(value, bool) or isinstance(value, float):
        raise JournalValidationError(
            f"{field} must be Decimal or a decimal string, not float."
        )

    if not isinstance(value, (Decimal, str, int)):
        raise JournalValidationError(
            f"{field} must be Decimal or a decimal string."
        )

    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise JournalValidationError(
            f"{field} must be a valid decimal amount."
        )

    if not amount.is_finite():
        raise JournalValidationError(f"{field} must be finite.")

    if amount < ZERO:
        raise JournalValidationError(f"{field} cannot be negative.")

    if amount > MAX_AMOUNT:
        raise JournalValidationError(f"{field} exceeds Numeric(14,2).")

    try:
        rounded_amount = amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise JournalValidationError(
            f"{field} must fit the supported two-decimal precision."
        )

    if amount != rounded_amount:
        raise JournalValidationError(
            f"{field} cannot have more than two decimal places."
        )

    return amount


def validate_journal(
    company_id,
    journal_date,
    description,
    currency,
    lines,
    accounts,
    source_type="manual",
    source_id=None,
):
    """Validate a journal using plain dictionaries only.

    No ORM objects, sessions, queries, or database connections are used.
    Returns normalized data with Decimal debit and credit amounts.
    """

    company_id = _positive_company_id(company_id, "company_id")

    if not isinstance(journal_date, date):
        raise JournalValidationError("journal_date must be a date.")

    if isinstance(journal_date, __import__("datetime").datetime):
        raise JournalValidationError(
            "journal_date must be a date, not a datetime."
        )

    if not isinstance(description, str) or not description.strip():
        raise JournalValidationError("description is required.")

    if len(description.strip()) > 500:
        raise JournalValidationError(
            "description cannot exceed 500 characters."
        )

    if not isinstance(currency, str):
        raise JournalValidationError("currency must be a three-letter code.")

    currency = currency.strip().upper()

    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise JournalValidationError(
            "currency must be a three-letter alphabetic code."
        )

    if not isinstance(source_type, str) or not source_type.strip():
        raise JournalValidationError("source_type is required.")

    source_type = source_type.strip().lower()

    if len(source_type) > 40:
        raise JournalValidationError(
            "source_type cannot exceed 40 characters."
        )

    if source_id is not None:
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id <= 0
        ):
            raise JournalValidationError(
                "source_id must be a positive integer or None."
            )

    if not isinstance(lines, (list, tuple)) or len(lines) < 2:
        raise JournalValidationError(
            "A journal must contain at least two lines."
        )

    if not isinstance(accounts, dict):
        raise JournalValidationError(
            "accounts must be a dictionary keyed by account ID."
        )

    normalized_lines = []
    debit_total = ZERO
    credit_total = ZERO
    seen_line_numbers = set()

    for position, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise JournalValidationError(
                f"Line {position} must be a plain dictionary."
            )

        line_number = line.get("line_number", position)

        if (
            isinstance(line_number, bool)
            or not isinstance(line_number, int)
            or line_number <= 0
        ):
            raise JournalValidationError(
                f"Line {position} has an invalid line number."
            )

        if line_number in seen_line_numbers:
            raise JournalValidationError(
                f"Duplicate line number: {line_number}."
            )

        seen_line_numbers.add(line_number)

        account_id = line.get("account_id")

        if (
            isinstance(account_id, bool)
            or not isinstance(account_id, int)
            or account_id <= 0
        ):
            raise JournalValidationError(
                f"Line {position} has an invalid account ID."
            )

        account = accounts.get(account_id)

        if not isinstance(account, dict):
            raise JournalValidationError(
                f"Account {account_id} is missing or invalid."
            )

        if account.get("id") != account_id:
            raise JournalValidationError(
                f"Account {account_id} does not match its dictionary key."
            )

        if account.get("company_id") != company_id:
            raise JournalValidationError(
                f"Account {account_id} belongs to another company."
            )

        if account.get("is_active") is not True:
            raise JournalValidationError(
                f"Account {account_id} is inactive."
            )

        if account.get("allow_manual_posting") is not True:
            raise JournalValidationError(
                f"Account {account_id} does not allow manual posting."
            )

        has_children = any(
            isinstance(candidate, dict)
            and candidate.get("company_id") == company_id
            and candidate.get("parent_id") == account_id
            for candidate in accounts.values()
        )

        if has_children:
            raise JournalValidationError(
                f"Account {account_id} is a parent account."
            )

        debit = _decimal_amount(
            line.get("debit", ZERO),
            f"Line {position} debit",
        )
        credit = _decimal_amount(
            line.get("credit", ZERO),
            f"Line {position} credit",
        )

        if (debit > ZERO and credit > ZERO) or (
            debit == ZERO and credit == ZERO
        ):
            raise JournalValidationError(
                f"Line {position} must have exactly one positive side."
            )

        line_description = line.get("description")

        if line_description is not None:
            if not isinstance(line_description, str):
                raise JournalValidationError(
                    f"Line {position} description must be text."
                )
            line_description = line_description.strip() or None
            if line_description is not None and len(line_description) > 300:
                raise JournalValidationError(
                    f"Line {position} description is too long."
                )

        normalized_lines.append({
            "line_number": line_number,
            "account_id": account_id,
            "description": line_description,
            "debit": debit,
            "credit": credit,
        })

        debit_total += debit
        credit_total += credit

    if debit_total != credit_total:
        raise JournalValidationError(
            "Journal is not balanced: "
            f"debits={debit_total}, credits={credit_total}."
        )

    if debit_total <= ZERO:
        raise JournalValidationError(
            "Journal total must be greater than zero."
        )

    return {
        "company_id": company_id,
        "journal_date": journal_date,
        "description": description.strip(),
        "currency": currency,
        "source_type": source_type,
        "source_id": source_id,
        "lines": normalized_lines,
        "total_debit": debit_total,
        "total_credit": credit_total,
    }
