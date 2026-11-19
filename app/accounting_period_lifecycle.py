"""Pure lifecycle and audit-event preparation for accounting calendars."""

from datetime import datetime


class AccountingPeriodLifecycleError(ValueError):
    pass


def _plain_dict(value, field):
    if type(value) is not dict:
        raise AccountingPeriodLifecycleError(
            f"{field} must be a plain dictionary."
        )
    return value


def _positive_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AccountingPeriodLifecycleError(
            f"{field} must be a positive integer."
        )
    return value


def _actor(actor_company_id, actor_id, company_id):
    actor_company_id = _positive_id(
        actor_company_id, "actor_company_id"
    )
    actor_id = _positive_id(actor_id, "actor_id")

    if actor_company_id != company_id:
        raise AccountingPeriodLifecycleError(
            "The actor does not belong to this company."
        )

    return actor_id


def _timestamp(value):
    if not isinstance(value, datetime):
        raise AccountingPeriodLifecycleError(
            "performed_at must be a datetime."
        )
    return value


def _reason(value):
    if not isinstance(value, str) or not value.strip():
        raise AccountingPeriodLifecycleError(
            "An audit reason is required."
        )
    value = value.strip()
    if len(value) > 500:
        raise AccountingPeriodLifecycleError(
            "Audit reason cannot exceed 500 characters."
        )
    return value


def _transition(record, action, actor_id, performed_at):
    status = record.get("status")
    closed_at = record.get("closed_at")
    closed_by_id = record.get("closed_by_id")

    if action == "close":
        if status != "open":
            raise AccountingPeriodLifecycleError(
                "Only an open accounting record can be closed."
            )
        if closed_at is not None or closed_by_id is not None:
            raise AccountingPeriodLifecycleError(
                "Open record has unexpected closing metadata."
            )
        return {
            "status": "closed",
            "closed_at": performed_at,
            "closed_by_id": actor_id,
        }

    if action == "reopen":
        if status != "closed":
            raise AccountingPeriodLifecycleError(
                "Only a closed accounting record can be reopened."
            )
        if closed_at is None or closed_by_id is None:
            raise AccountingPeriodLifecycleError(
                "Closed record is missing its closing metadata."
            )
        return {
            "status": "open",
            "closed_at": None,
            "closed_by_id": None,
        }

    raise AccountingPeriodLifecycleError(
        "Action must be 'close' or 'reopen'."
    )


def prepare_period_transition(
    period,
    financial_year,
    actor_company_id,
    actor_id,
    performed_at,
    action,
    reason,
):
    """Prepare a period state change and its immutable audit event."""

    period = _plain_dict(period, "period")
    financial_year = _plain_dict(financial_year, "financial_year")

    period_id = _positive_id(period.get("id"), "period.id")
    company_id = _positive_id(
        period.get("company_id"), "period.company_id"
    )
    year_id = _positive_id(
        financial_year.get("id"), "financial_year.id"
    )

    if financial_year.get("company_id") != company_id:
        raise AccountingPeriodLifecycleError(
            "Period and financial year belong to different companies."
        )

    if period.get("financial_year_id") != year_id:
        raise AccountingPeriodLifecycleError(
            "Period is linked to a different financial year."
        )

    if financial_year.get("status") != "open":
        raise AccountingPeriodLifecycleError(
            "Periods cannot be changed while their financial year is closed."
        )

    actor_id = _actor(actor_company_id, actor_id, company_id)
    performed_at = _timestamp(performed_at)
    reason = _reason(reason)

    transition = _transition(
        period, action, actor_id, performed_at
    )

    event = {
        "company_id": company_id,
        "financial_year_id": None,
        "accounting_period_id": period_id,
        "event_type": "closed" if action == "close" else "reopened",
        "performed_by_id": actor_id,
        "performed_at": performed_at,
        "reason": reason,
    }

    return {
        "period_id": period_id,
        "transition": transition,
        "event": event,
    }


def prepare_financial_year_transition(
    financial_year,
    periods,
    actor_company_id,
    actor_id,
    performed_at,
    action,
    reason,
):
    """Prepare a financial-year state change and its audit event.

    Every period must be closed before a financial year can be closed.
    Reopening a financial year leaves its periods closed.
    """

    financial_year = _plain_dict(
        financial_year, "financial_year"
    )

    if not isinstance(periods, (list, tuple)) or not periods:
        raise AccountingPeriodLifecycleError(
            "A financial year must contain accounting periods."
        )

    year_id = _positive_id(
        financial_year.get("id"), "financial_year.id"
    )
    company_id = _positive_id(
        financial_year.get("company_id"),
        "financial_year.company_id",
    )

    for index, raw_period in enumerate(periods):
        period = _plain_dict(raw_period, f"periods[{index}]")

        if period.get("company_id") != company_id:
            raise AccountingPeriodLifecycleError(
                "A period belongs to another company."
            )

        if period.get("financial_year_id") != year_id:
            raise AccountingPeriodLifecycleError(
                "A period belongs to another financial year."
            )

        if period.get("status") != "closed":
            raise AccountingPeriodLifecycleError(
                "All accounting periods must be closed first."
            )

    actor_id = _actor(actor_company_id, actor_id, company_id)
    performed_at = _timestamp(performed_at)
    reason = _reason(reason)

    transition = _transition(
        financial_year, action, actor_id, performed_at
    )

    event = {
        "company_id": company_id,
        "financial_year_id": year_id,
        "accounting_period_id": None,
        "event_type": "closed" if action == "close" else "reopened",
        "performed_by_id": actor_id,
        "performed_at": performed_at,
        "reason": reason,
    }

    return {
        "financial_year_id": year_id,
        "transition": transition,
        "event": event,
    }
