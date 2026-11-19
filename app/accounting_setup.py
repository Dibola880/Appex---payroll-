"""Atomic company accounting chart and financial-calendar setup."""

import calendar
from datetime import date, datetime, timedelta

from . import db
from .accounting_chart import prepare_company_accounts
from .accounting_period_validation import (
    validate_financial_year_schedule,
)
from .models import (
    Account,
    AccountingPeriod,
    AccountingPeriodEvent,
    Company,
    FinancialYear,
    User,
)
from .subscription_entitlements import has_feature


class AccountingSetupError(ValueError):
    """Raised when accounting setup is unsafe or inconsistent."""


def _require_date(value, field):
    if not isinstance(value, date) or isinstance(value, datetime):
        raise AccountingSetupError(
            f"{field} must be a valid date."
        )
    return value


def _build_monthly_periods(company_id, start_date, end_date):
    """Build calendar-month periods, allowing partial first and last months."""
    periods = []
    current = start_date
    number = 1

    while current <= end_date:
        month_end = date(
            current.year,
            current.month,
            calendar.monthrange(current.year, current.month)[1],
        )
        period_end = min(end_date, month_end)

        periods.append({
            "company_id": company_id,
            "financial_year_id": None,
            "period_number": number,
            "name": f"{calendar.month_name[current.month]} {current.year}",
            "start_date": current,
            "end_date": period_end,
            "status": "open",
        })

        if period_end == end_date:
            break

        current = period_end + timedelta(days=1)
        number += 1

    return periods


def _account_conflict(message):
    raise AccountingSetupError(
        f"Chart-of-accounts reconciliation stopped: {message}"
    )


def _reconcile_company_accounts(company_id, existing_accounts):
    """Add missing standard accounts without replacing existing records."""
    templates = prepare_company_accounts(company_id)

    by_code = {}
    by_system_code = {}

    for account in existing_accounts:
        code = account.account_code
        system_code = account.system_code

        if code in by_code:
            _account_conflict(
                f"duplicate existing account code {code!r}."
            )
        by_code[code] = account

        if system_code is not None:
            if system_code in by_system_code:
                _account_conflict(
                    f"duplicate existing system code {system_code!r}."
                )
            by_system_code[system_code] = account

    templates_by_code = {
        item["account_code"]: item
        for item in templates
    }
    resolved = {}
    missing = []

    # First identify all existing standard accounts. A system code is the
    # stable identity; account codes and names may have been customized.
    for template in templates:
        code = template["account_code"]
        system_code = template["system_code"]

        code_match = by_code.get(code)
        system_match = by_system_code.get(system_code)

        if (
            code_match is not None
            and system_match is not None
            and code_match.id != system_match.id
        ):
            _account_conflict(
                f"standard code {code!r} and system code "
                f"{system_code!r} identify different records."
            )

        if system_match is not None:
            if (
                system_match.account_type != template["account_type"]
                or system_match.normal_balance != template["normal_balance"]
            ):
                _account_conflict(
                    f"standard account {system_code!r} has an "
                    "incompatible account type or normal balance."
                )

            resolved[system_code] = system_match

        elif code_match is not None:
            _account_conflict(
                f"account code {code!r} is already used by an account "
                "without the matching standard system code."
            )
        else:
            missing.append(template)

    created_count = 0

    # Create missing root accounts first so their IDs are available.
    for template in missing:
        if template["parent_code"] is not None:
            continue

        account = Account(
            company_id=company_id,
            account_code=template["account_code"],
            name=template["name"],
            account_type=template["account_type"],
            normal_balance=template["normal_balance"],
            parent_id=None,
            system_code=template["system_code"],
            allow_manual_posting=template["allow_manual_posting"],
        )
        db.session.add(account)
        db.session.flush()

        resolved[template["system_code"]] = account
        created_count += 1

    # Validate existing root relationships before creating child accounts.
    for template in templates:
        if template["parent_code"] is not None:
            continue

        account = resolved[template["system_code"]]
        if account.parent_id is not None:
            _account_conflict(
                f"standard root account {template['system_code']!r} "
                "already has a parent."
            )

    # Create or validate one-level child relationships.
    for template in templates:
        parent_code = template["parent_code"]
        if parent_code is None:
            continue

        parent_template = templates_by_code.get(parent_code)
        if parent_template is None:
            _account_conflict(
                f"standard parent code {parent_code!r} is missing."
            )

        parent = resolved.get(parent_template["system_code"])
        if parent is None:
            _account_conflict(
                f"standard parent {parent_code!r} could not be resolved."
            )

        account = resolved.get(template["system_code"])

        if account is not None:
            if account.parent_id != parent.id:
                _account_conflict(
                    f"standard account {template['system_code']!r} "
                    "has a different parent relationship."
                )
            continue

        account = Account(
            company_id=company_id,
            account_code=template["account_code"],
            name=template["name"],
            account_type=template["account_type"],
            normal_balance=template["normal_balance"],
            parent_id=parent.id,
            system_code=template["system_code"],
            allow_manual_posting=template["allow_manual_posting"],
        )
        db.session.add(account)
        db.session.flush()

        resolved[template["system_code"]] = account
        created_count += 1

    return created_count


def _year_as_dict(year):
    return {
        "id": year.id,
        "company_id": year.company_id,
        "name": year.name,
        "start_date": year.start_date,
        "end_date": year.end_date,
        "status": year.status,
    }


def _period_as_dict(period):
    return {
        "company_id": period.company_id,
        "financial_year_id": period.financial_year_id,
        "period_number": period.period_number,
        "name": period.name,
        "start_date": period.start_date,
        "end_date": period.end_date,
        "status": period.status,
    }


def _assert_existing_setup_complete(
    company_id,
    year,
    expected_periods,
    existing_years,
):
    """Accept an exact prior setup; reject partial or unaudited schedules."""
    periods = (
        AccountingPeriod.query
        .filter_by(
            company_id=company_id,
            financial_year_id=year.id,
        )
        .order_by(AccountingPeriod.period_number.asc())
        .with_for_update()
        .populate_existing()
        .all()
    )

    if len(periods) != len(expected_periods):
        raise AccountingSetupError(
            "A financial year with this date range already exists, "
            "but its accounting-period schedule is incomplete."
        )

    for actual, expected in zip(periods, expected_periods):
        if (
            actual.company_id != company_id
            or actual.financial_year_id != year.id
            or actual.period_number != expected["period_number"]
            or actual.name != expected["name"]
            or actual.start_date != expected["start_date"]
            or actual.end_date != expected["end_date"]
        ):
            raise AccountingSetupError(
                "The existing accounting-period schedule differs from "
                "the requested calendar. No records were changed."
            )

    other_years = [
        _year_as_dict(item)
        for item in existing_years
        if item.id != year.id
    ]

    validate_financial_year_schedule(
        company_id,
        _year_as_dict(year),
        [_period_as_dict(item) for item in periods],
        existing_financial_years=other_years,
    )

    if year.status == "closed" and any(
        period.status != "closed" for period in periods
    ):
        raise AccountingSetupError(
            "A closed financial year cannot contain an open accounting period."
        )

    year_open_events = (
        AccountingPeriodEvent.query
        .filter_by(
            company_id=company_id,
            financial_year_id=year.id,
            event_type="opened",
        )
        .filter(
            AccountingPeriodEvent.accounting_period_id.is_(None)
        )
        .with_for_update()
        .all()
    )

    if len(year_open_events) != 1:
        raise AccountingSetupError(
            "The existing financial year does not have exactly one "
            "opening audit event. Manual review is required."
        )

    period_ids = [item.id for item in periods]
    period_open_events = (
        AccountingPeriodEvent.query
        .filter(
            AccountingPeriodEvent.company_id == company_id,
            AccountingPeriodEvent.financial_year_id.is_(None),
            AccountingPeriodEvent.accounting_period_id.in_(period_ids),
            AccountingPeriodEvent.event_type == "opened",
        )
        .with_for_update()
        .all()
    )

    opening_counts = {}
    for event in period_open_events:
        opening_counts[event.accounting_period_id] = (
            opening_counts.get(event.accounting_period_id, 0) + 1
        )

    if any(opening_counts.get(item.id, 0) != 1 for item in periods):
        raise AccountingSetupError(
            "One or more existing accounting periods do not have "
            "exactly one opening audit event. Manual review is required."
        )

    return periods


def setup_company_accounting(
    company_id,
    actor_id,
    financial_year_name,
    start_date,
    end_date,
):
    """Atomically reconcile a company's chart and create its first calendar.

    Existing customized account records are preserved. An exact existing
    financial-year setup is treated as an idempotent retry only when its
    periods and opening audit events are complete.
    """
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise AccountingSetupError(
            "A valid company ID is required."
        )

    if (
        isinstance(actor_id, bool)
        or not isinstance(actor_id, int)
        or actor_id <= 0
    ):
        raise AccountingSetupError(
            "A valid company administrator ID is required."
        )

    if not isinstance(financial_year_name, str):
        raise AccountingSetupError(
            "A financial-year name is required."
        )

    financial_year_name = financial_year_name.strip()
    if not financial_year_name or len(financial_year_name) > 40:
        raise AccountingSetupError(
            "The financial-year name must contain 1 to 40 characters."
        )

    start_date = _require_date(start_date, "Financial-year start date")
    end_date = _require_date(end_date, "Financial-year end date")

    if start_date > end_date:
        raise AccountingSetupError(
            "The financial-year end date must not precede its start date."
        )

    try:
        # Lock order begins with the company row. PostgreSQL serializes
        # concurrent setup attempts for the same company at this point.
        company = (
            Company.query
            .filter_by(id=company_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

        if company is None:
            raise AccountingSetupError(
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
            raise AccountingSetupError(
                "An active company administrator belonging to this company is required."
            )

        if not has_feature(company, "accounting"):
            raise AccountingSetupError(
                "This company does not have an active accounting entitlement."
            )

        existing_accounts = (
            Account.query
            .filter_by(company_id=company_id)
            .order_by(Account.id.asc())
            .with_for_update()
            .populate_existing()
            .all()
        )

        existing_years = (
            FinancialYear.query
            .filter_by(company_id=company_id)
            .order_by(FinancialYear.start_date.asc())
            .with_for_update()
            .populate_existing()
            .all()
        )

        expected_periods = _build_monthly_periods(
            company_id,
            start_date,
            end_date,
        )

        matching_dates = [
            item for item in existing_years
            if item.start_date == start_date
            and item.end_date == end_date
        ]

        matching_names = [
            item for item in existing_years
            if item.name == financial_year_name
        ]

        if len(matching_dates) > 1:
            raise AccountingSetupError(
                "Multiple financial years already use the requested dates."
            )

        existing_year = matching_dates[0] if matching_dates else None

        if existing_year is not None:
            if existing_year.name != financial_year_name:
                raise AccountingSetupError(
                    "A financial year already exists for these dates "
                    "under a different name."
                )

            periods = _assert_existing_setup_complete(
                company_id,
                existing_year,
                expected_periods,
                existing_years,
            )

            already_configured = True

        else:
            if matching_names:
                raise AccountingSetupError(
                    "This financial-year name is already in use "
                    "for a different date range."
                )

            schedule = validate_financial_year_schedule(
                company_id,
                {
                    "company_id": company_id,
                    "name": financial_year_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "open",
                },
                expected_periods,
                existing_financial_years=[
                    _year_as_dict(item) for item in existing_years
                ],
            )

            already_configured = False
            periods = []

        accounts_created = _reconcile_company_accounts(
            company_id,
            existing_accounts,
        )

        if not already_configured:
            financial_year = FinancialYear(
                company_id=company_id,
                name=schedule["name"],
                start_date=schedule["start_date"],
                end_date=schedule["end_date"],
                status=schedule["status"],
            )
            db.session.add(financial_year)
            db.session.flush()

            for period_data in schedule["periods"]:
                period = AccountingPeriod(
                    company_id=company_id,
                    financial_year_id=financial_year.id,
                    period_number=period_data["period_number"],
                    name=period_data["name"],
                    start_date=period_data["start_date"],
                    end_date=period_data["end_date"],
                    status=period_data["status"],
                )
                db.session.add(period)
                periods.append(period)

            db.session.flush()

            performed_at = datetime.utcnow()
            reason = "Initial accounting setup"

            db.session.add(
                AccountingPeriodEvent(
                    company_id=company_id,
                    financial_year_id=financial_year.id,
                    accounting_period_id=None,
                    event_type="opened",
                    performed_by_id=actor_id,
                    performed_at=performed_at,
                    reason=reason,
                )
            )

            for period in periods:
                db.session.add(
                    AccountingPeriodEvent(
                        company_id=company_id,
                        financial_year_id=None,
                        accounting_period_id=period.id,
                        event_type="opened",
                        performed_by_id=actor_id,
                        performed_at=performed_at,
                        reason=reason,
                    )
                )

            db.session.flush()
        else:
            financial_year = existing_year

        db.session.commit()

        return {
            "financial_year": financial_year,
            "periods": periods,
            "accounts_created": accounts_created,
            "already_configured": already_configured,
        }

    except Exception:
        db.session.rollback()
        raise
