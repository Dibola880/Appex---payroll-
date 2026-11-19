"""Atomic persistence service for accounting period and year lifecycle changes."""

from datetime import datetime

from . import db
from .accounting_period_lifecycle import (
    prepare_period_transition,
    prepare_financial_year_transition,
)
from .models import (
    AccountingPeriod,
    AccountingPeriodEvent,
    Company,
    FinancialYear,
    User,
)
from .subscription_entitlements import has_feature


class AccountingLifecycleServiceError(ValueError):
    """Raised when an accounting lifecycle operation is unsafe."""


def _positive_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AccountingLifecycleServiceError(
            f"{field} must be a positive integer."
        )
    return value


def _period_snapshot(period):
    return {
        "id": period.id,
        "company_id": period.company_id,
        "financial_year_id": period.financial_year_id,
        "status": period.status,
        "closed_at": period.closed_at,
        "closed_by_id": period.closed_by_id,
    }


def _year_snapshot(year):
    return {
        "id": year.id,
        "company_id": year.company_id,
        "status": year.status,
        "closed_at": year.closed_at,
        "closed_by_id": year.closed_by_id,
    }


def _lock_company_and_actor(company_id, actor_id):
    """Lock and validate the company and its active accounting administrator."""

    company = (
        Company.query
        .filter_by(id=company_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if company is None:
        raise AccountingLifecycleServiceError(
            "The company could not be found."
        )

    actor = (
        User.query
        .filter_by(id=actor_id, company_id=company_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if (
        actor is None
        or actor.is_active is not True
        or actor.role != "company_admin"
    ):
        raise AccountingLifecycleServiceError(
            "An active company administrator belonging to this company is required."
        )

    if not has_feature(company, "accounting"):
        raise AccountingLifecycleServiceError(
            "This company does not have an active accounting entitlement."
        )

    return company, actor


def _apply_transition(record, transition):
    record.status = transition["status"]
    record.closed_at = transition["closed_at"]
    record.closed_by_id = transition["closed_by_id"]


def _persist_event(event_data):
    """Insert a new audit event; existing audit events are never modified."""

    db.session.add(AccountingPeriodEvent(**event_data))


def _finish_operation(record, transition, event_data):
    _apply_transition(record, transition)
    _persist_event(event_data)
    db.session.flush()
    db.session.commit()
    return record


def _period_operation(
    company_id,
    period_id,
    actor_id,
    reason,
    action,
    performed_at=None,
):
    company_id = _positive_id(company_id, "company_id")
    period_id = _positive_id(period_id, "period_id")
    actor_id = _positive_id(actor_id, "actor_id")
    if not isinstance(reason, str) or not reason.strip():
        raise AccountingLifecycleServiceError("An audit reason is required.")

    if performed_at is None:
        performed_at = datetime.utcnow()

    try:
        _lock_company_and_actor(company_id, actor_id)

        # Read the parent ID first, then lock parent before child.
        # The company row lock serializes same-company lifecycle operations.
        year_id = (
            db.session.query(AccountingPeriod.financial_year_id)
            .filter_by(id=period_id, company_id=company_id)
            .scalar()
        )
        if year_id is None:
            raise AccountingLifecycleServiceError(
                "The accounting period could not be found."
            )

        year = (
            FinancialYear.query
            .filter_by(id=year_id, company_id=company_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if year is None:
            raise AccountingLifecycleServiceError(
                "The accounting period could not be found."
            )

        period = (
            AccountingPeriod.query
            .filter_by(
                id=period_id,
                company_id=company_id,
                financial_year_id=year.id,
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        if period is None:
            raise AccountingLifecycleServiceError(
                "The accounting period could not be found."
            )

        prepared = prepare_period_transition(
            period=_period_snapshot(period),
            financial_year=_year_snapshot(year),
            actor_company_id=company_id,
            actor_id=actor_id,
            performed_at=performed_at,
            action=action,
            reason=reason,
        )

        return _finish_operation(
            period,
            prepared["transition"],
            prepared["event"],
        )

    except Exception:
        db.session.rollback()
        raise


def _financial_year_operation(
    company_id,
    financial_year_id,
    actor_id,
    reason,
    action,
    performed_at=None,
):
    company_id = _positive_id(company_id, "company_id")
    financial_year_id = _positive_id(
        financial_year_id, "financial_year_id"
    )
    actor_id = _positive_id(actor_id, "actor_id")
    if not isinstance(reason, str) or not reason.strip():
        raise AccountingLifecycleServiceError("An audit reason is required.")

    if performed_at is None:
        performed_at = datetime.utcnow()

    try:
        _lock_company_and_actor(company_id, actor_id)

        year = (
            FinancialYear.query
            .filter_by(id=financial_year_id, company_id=company_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if year is None:
            raise AccountingLifecycleServiceError(
                "The financial year could not be found."
            )

        periods = (
            AccountingPeriod.query
            .filter_by(
                company_id=company_id,
                financial_year_id=financial_year_id,
            )
            .order_by(
                AccountingPeriod.period_number.asc(),
                AccountingPeriod.id.asc(),
            )
            .with_for_update()
            .populate_existing()
            .all()
        )

        prepared = prepare_financial_year_transition(
            financial_year=_year_snapshot(year),
            periods=[_period_snapshot(period) for period in periods],
            actor_company_id=company_id,
            actor_id=actor_id,
            performed_at=performed_at,
            action=action,
            reason=reason,
        )

        return _finish_operation(
            year,
            prepared["transition"],
            prepared["event"],
        )

    except Exception:
        db.session.rollback()
        raise


def close_accounting_period(
    company_id, period_id, actor_id, reason, performed_at=None
):
    """Close one open period and append its audit event atomically."""

    return _period_operation(
        company_id, period_id, actor_id, reason, "close", performed_at
    )


def reopen_accounting_period(
    company_id, period_id, actor_id, reason, performed_at=None
):
    """Reopen one closed period while its financial year remains open."""

    return _period_operation(
        company_id, period_id, actor_id, reason, "reopen", performed_at
    )


def close_financial_year(
    company_id, financial_year_id, actor_id, reason, performed_at=None
):
    """Close a financial year only after all its periods are closed."""

    return _financial_year_operation(
        company_id,
        financial_year_id,
        actor_id,
        reason,
        "close",
        performed_at,
    )


def reopen_financial_year(
    company_id, financial_year_id, actor_id, reason, performed_at=None
):
    """Reopen a financial year without reopening its accounting periods."""

    return _financial_year_operation(
        company_id,
        financial_year_id,
        actor_id,
        reason,
        "reopen",
        performed_at,
    )
