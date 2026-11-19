"""Payroll-to-accounting draft journal integration."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import Account, Employee, JournalEntry, Payslip
from .journal_service import create_journal


ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(value, field):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is missing or invalid.")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} is not a valid monetary amount.")

    if not amount.is_finite() or amount < ZERO:
        raise ValueError(
            f"{field} must be finite and non-negative."
        )

    try:
        rounded = amount.quantize(CENT)
    except InvalidOperation:
        raise ValueError(
            f"{field} exceeds supported monetary precision."
        )

    if amount != rounded:
        raise ValueError(
            f"{field} has more than two decimal places."
        )

    return rounded


def create_payroll_journal(payroll_run, actor_id):
    """Create one balanced draft journal from persisted payslips."""

    company_id = payroll_run.company_id
    run_id = payroll_run.id

    if (
        not isinstance(payroll_run.pay_date, date)
        or isinstance(payroll_run.pay_date, datetime)
    ):
        raise ValueError("A valid payroll pay date is required.")

    currency = payroll_run.currency
    if (
        not isinstance(currency, str)
        or len(currency.strip()) != 3
        or not currency.strip().isascii()
        or not currency.strip().isalpha()
    ):
        raise ValueError("A valid payroll currency is required.")

    existing = JournalEntry.query.filter_by(
        company_id=company_id,
        source_type="payroll",
        source_id=run_id,
    ).first()

    if existing is not None:
        raise ValueError(
            "An accounting journal already exists for this payroll."
        )

    payslips = Payslip.query.filter_by(
        payroll_run_id=run_id
    ).order_by(Payslip.id).all()

    if not payslips:
        raise ValueError(
            "Cannot create a payroll journal without payslips."
        )

    employee_ids = [p.employee_id for p in payslips]

    employees = {
        employee.id: employee
        for employee in Employee.query.filter(
            Employee.id.in_(employee_ids)
        ).all()
    }

    if any(
        employee_id not in employees
        or employees[employee_id].company_id != company_id
        for employee_id in employee_ids
    ):
        raise ValueError(
            "Payroll payslips contain an employee outside this company."
        )

    totals = {
        "gross_pay": ZERO,
        "employer_uif": ZERO,
        "tax_deductions": ZERO,
        "employee_uif": ZERO,
        "other_deductions": ZERO,
        "net_pay": ZERO,
    }

    field_mapping = {
        "gross_pay": "gross_pay",
        "employer_uif": "employer_uif",
        "tax_deductions": "tax_deductions",
        "employee_uif": "uif",
        "other_deductions": "other_deductions",
        "net_pay": "net_pay",
    }

    for payslip in payslips:
        loan = _money(
            payslip.loan_repayment,
            "Payslip loan repayment",
        )

        if loan > ZERO:
            raise ValueError(
                "Accounting-enabled payroll cannot include loan "
                "repayments until loan disbursement accounting "
                "is implemented."
            )

        for total_field, payslip_field in field_mapping.items():
            totals[total_field] += _money(
                getattr(payslip, payslip_field),
                f"Payslip {payslip_field}",
            )

    for field in totals:
        totals[field] = _money(
            totals[field],
            f"Payroll total {field}",
        )

    required_codes = {
        "SALARIES_WAGES",
        "EMPLOYER_UIF",
        "PAYE_PAYABLE",
        "UIF_PAYABLE",
        "OTHER_PAYROLL_DEDUCTIONS",
        "NET_SALARIES_PAYABLE",
    }

    accounts = Account.query.filter(
        Account.company_id == company_id,
        Account.system_code.in_(required_codes),
    ).all()

    accounts_by_code = {}

    for account in accounts:
        if account.system_code in accounts_by_code:
            raise ValueError(
                "Duplicate company account configuration: "
                f"{account.system_code}."
            )

        if not account.is_active or not account.allow_manual_posting:
            raise ValueError(
                f"Required payroll account {account.system_code} "
                "must be active and allow posting."
            )

        accounts_by_code[account.system_code] = account

    missing = required_codes - set(accounts_by_code)

    if missing:
        raise ValueError(
            "Configure the required payroll accounting accounts first: "
            + ", ".join(sorted(missing))
        )

    lines = []

    def add_line(code, description, debit=ZERO, credit=ZERO):
        debit = _money(debit, f"{code} debit")
        credit = _money(credit, f"{code} credit")

        if debit == ZERO and credit == ZERO:
            return

        lines.append({
            "account_id": accounts_by_code[code].id,
            "description": description,
            "debit": debit,
            "credit": credit,
        })

    add_line(
        "SALARIES_WAGES",
        "Payroll gross earnings",
        debit=totals["gross_pay"],
    )

    add_line(
        "EMPLOYER_UIF",
        "Employer UIF expense",
        debit=totals["employer_uif"],
    )

    add_line(
        "PAYE_PAYABLE",
        "PAYE withheld",
        credit=totals["tax_deductions"],
    )

    add_line(
        "UIF_PAYABLE",
        "Employee and employer UIF",
        credit=totals["employee_uif"] + totals["employer_uif"],
    )

    add_line(
        "OTHER_PAYROLL_DEDUCTIONS",
        "Other payroll deductions",
        credit=totals["other_deductions"],
    )

    add_line(
        "NET_SALARIES_PAYABLE",
        "Net salaries payable",
        credit=totals["net_pay"],
    )

    if len(lines) < 2:
        raise ValueError(
            "Payroll totals do not produce a valid accounting journal."
        )

    return create_journal(
        company_id=company_id,
        actor_id=actor_id,
        journal_number=f"PAYROLL-{run_id}",
        journal_date=payroll_run.pay_date,
        description=f"Payroll journal - {payroll_run.pay_period}",
        currency=currency.strip().upper(),
        lines=lines,
        source_type="payroll",
        source_id=run_id,
    )
