"""Pure in-memory validation for company accounting calendars."""

from datetime import date, datetime, timedelta


class AccountingPeriodValidationError(ValueError):
    pass


def _positive_company_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AccountingPeriodValidationError(
            f"{field} must be a positive integer."
        )
    return value


def _plain_dict(value, field):
    if type(value) is not dict:
        raise AccountingPeriodValidationError(
            f"{field} must be a plain dictionary."
        )
    return value


def _valid_date(value, field):
    if not isinstance(value, date) or isinstance(value, datetime):
        raise AccountingPeriodValidationError(
            f"{field} must be a date, not a datetime."
        )
    return value


def _valid_status(value, field):
    if value not in ("open", "closed"):
        raise AccountingPeriodValidationError(
            f"{field} must be 'open' or 'closed'."
        )
    return value


def _overlaps(start_a, end_a, start_b, end_b):
    return start_a <= end_b and start_b <= end_a


def validate_financial_year_schedule(
    company_id,
    financial_year,
    periods,
    existing_financial_years=(),
):
    """Validate one financial year and its complete period schedule.

    All inputs must be plain dictionaries and ordinary Python collections.
    Periods must cover every day of the financial year exactly once.
    Existing financial years for the same company may not overlap.
    No database access or ORM operations are performed.
    """

    company_id = _positive_company_id(company_id, "company_id")
    financial_year = _plain_dict(financial_year, "financial_year")

    if not isinstance(periods, (list, tuple)) or not periods:
        raise AccountingPeriodValidationError(
            "At least one accounting period is required."
        )

    if not isinstance(existing_financial_years, (list, tuple)):
        raise AccountingPeriodValidationError(
            "existing_financial_years must be a list or tuple."
        )

    name = financial_year.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AccountingPeriodValidationError(
            "Financial-year name is required."
        )
    if len(name.strip()) > 40:
        raise AccountingPeriodValidationError(
            "Financial-year name cannot exceed 40 characters."
        )

    if financial_year.get("company_id") != company_id:
        raise AccountingPeriodValidationError(
            "Financial year belongs to another company."
        )

    year_start = _valid_date(
        financial_year.get("start_date"), "financial_year.start_date"
    )
    year_end = _valid_date(
        financial_year.get("end_date"), "financial_year.end_date"
    )
    year_status = _valid_status(
        financial_year.get("status", "open"),
        "financial_year.status",
    )

    if year_start > year_end:
        raise AccountingPeriodValidationError(
            "Financial-year start_date must not be after end_date."
        )

    year_id = financial_year.get("id")
    if year_id is not None:
        _positive_company_id(year_id, "financial_year.id")

    for index, existing in enumerate(existing_financial_years):
        existing = _plain_dict(
            existing, f"existing_financial_years[{index}]"
        )

        if existing.get("company_id") != company_id:
            raise AccountingPeriodValidationError(
                "Existing financial year belongs to another company."
            )

        existing_id = existing.get("id")
        if year_id is not None and existing_id == year_id:
            continue

        existing_start = _valid_date(
            existing.get("start_date"),
            f"existing_financial_years[{index}].start_date",
        )
        existing_end = _valid_date(
            existing.get("end_date"),
            f"existing_financial_years[{index}].end_date",
        )

        if existing_start > existing_end:
            raise AccountingPeriodValidationError(
                "An existing financial year has invalid dates."
            )

        if _overlaps(
            year_start, year_end, existing_start, existing_end
        ):
            raise AccountingPeriodValidationError(
                "Financial years cannot overlap within a company."
            )

    normalized_periods = []
    seen_numbers = set()

    for index, raw_period in enumerate(periods):
        period = _plain_dict(raw_period, f"periods[{index}]")

        if period.get("company_id") != company_id:
            raise AccountingPeriodValidationError(
                f"Period {index + 1} belongs to another company."
            )

        period_year_id = period.get("financial_year_id")
        if year_id is not None and period_year_id != year_id:
            raise AccountingPeriodValidationError(
                f"Period {index + 1} belongs to another financial year."
            )

        number = period.get("period_number")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number <= 0
        ):
            raise AccountingPeriodValidationError(
                f"Period {index + 1} must have a positive period number."
            )

        if number in seen_numbers:
            raise AccountingPeriodValidationError(
                "Period numbers must be unique within a financial year."
            )
        seen_numbers.add(number)

        period_name = period.get("name")
        if not isinstance(period_name, str) or not period_name.strip():
            raise AccountingPeriodValidationError(
                f"Period {number} requires a name."
            )
        if len(period_name.strip()) > 80:
            raise AccountingPeriodValidationError(
                f"Period {number} name cannot exceed 80 characters."
            )

        start = _valid_date(
            period.get("start_date"),
            f"periods[{index}].start_date",
        )
        end = _valid_date(
            period.get("end_date"),
            f"periods[{index}].end_date",
        )

        if start > end:
            raise AccountingPeriodValidationError(
                f"Period {number} has an invalid date range."
            )

        if start < year_start or end > year_end:
            raise AccountingPeriodValidationError(
                f"Period {number} falls outside its financial year."
            )

        status = _valid_status(
            period.get("status", "open"),
            f"periods[{index}].status",
        )

        normalized_periods.append({
            "company_id": company_id,
            "financial_year_id": period_year_id,
            "period_number": number,
            "name": period_name.strip(),
            "start_date": start,
            "end_date": end,
            "status": status,
        })

    normalized_periods.sort(
        key=lambda item: (item["start_date"], item["period_number"])
    )

    expected_start = year_start

    for index, period in enumerate(normalized_periods, start=1):
        if period["period_number"] != index:
            raise AccountingPeriodValidationError(
                "Period numbers must be sequential from 1 in date order."
            )

        if period["start_date"] != expected_start:
            raise AccountingPeriodValidationError(
                "Accounting periods must be continuous without gaps or overlaps."
            )

        if index < len(normalized_periods):
            if period["end_date"] == date.max:
                raise AccountingPeriodValidationError(
                    "A non-final accounting period cannot end at the maximum supported date."
                )
            expected_start = period["end_date"] + timedelta(days=1)

    if normalized_periods[-1]["end_date"] != year_end:
        raise AccountingPeriodValidationError(
            "Accounting periods must cover the entire financial year."
        )

    return {
        "company_id": company_id,
        "name": name.strip(),
        "start_date": year_start,
        "end_date": year_end,
        "status": year_status,
        "periods": normalized_periods,
    }


def assert_journal_date_postable(
    company_id,
    journal_date,
    financial_years,
    periods,
):
    """Require a journal date to fall in exactly one open period and year.

    Inputs must be plain dictionaries and ordinary Python collections.
    No ORM objects, database access, or SQL operations are used.
    """

    company_id = _positive_company_id(company_id, "company_id")
    journal_date = _valid_date(journal_date, "journal_date")

    if not isinstance(financial_years, (list, tuple)):
        raise AccountingPeriodValidationError(
            "financial_years must be a list or tuple."
        )

    if not isinstance(periods, (list, tuple)):
        raise AccountingPeriodValidationError(
            "periods must be a list or tuple."
        )

    matching_years = []

    for index, raw_year in enumerate(financial_years):
        year = _plain_dict(
            raw_year, f"financial_years[{index}]"
        )

        if year.get("company_id") != company_id:
            raise AccountingPeriodValidationError(
                "Financial-year input contains another company's record."
            )

        year_id = _positive_company_id(
            year.get("id"), f"financial_years[{index}].id"
        )
        start = _valid_date(
            year.get("start_date"),
            f"financial_years[{index}].start_date",
        )
        end = _valid_date(
            year.get("end_date"),
            f"financial_years[{index}].end_date",
        )

        if start > end:
            raise AccountingPeriodValidationError(
                "Financial year has an invalid date range."
            )

        if start <= journal_date <= end:
            matching_years.append(year)

    if len(matching_years) != 1:
        raise AccountingPeriodValidationError(
            "Journal date must belong to exactly one financial year."
        )

    year = matching_years[0]
    year_id = year["id"]

    if year.get("status") != "open":
        raise AccountingPeriodValidationError(
            "Cannot post into a closed financial year."
        )

    matching_periods = []

    for index, raw_period in enumerate(periods):
        period = _plain_dict(
            raw_period, f"periods[{index}]"
        )

        if period.get("company_id") != company_id:
            raise AccountingPeriodValidationError(
                "Period input contains another company's record."
            )

        period_year_id = period.get("financial_year_id")

        if period_year_id != year_id:
            continue

        start = _valid_date(
            period.get("start_date"),
            f"periods[{index}].start_date",
        )
        end = _valid_date(
            period.get("end_date"),
            f"periods[{index}].end_date",
        )

        if start > end:
            raise AccountingPeriodValidationError(
                "Accounting period has an invalid date range."
            )

        if start <= journal_date <= end:
            matching_periods.append(period)

    if len(matching_periods) != 1:
        raise AccountingPeriodValidationError(
            "Journal date must belong to exactly one accounting period."
        )

    period = matching_periods[0]

    if period.get("status") != "open":
        raise AccountingPeriodValidationError(
            "Cannot post into a closed accounting period."
        )

    return {
        "company_id": company_id,
        "financial_year_id": year_id,
        "accounting_period_id": _positive_company_id(
            period.get("id"), "accounting_period.id"
        ),
        "journal_date": journal_date,
    }
