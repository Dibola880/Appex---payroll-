from decimal import Decimal, ROUND_HALF_UP


# ============================================================
# SOUTH AFRICAN PAYROLL CALCULATOR
# TAX YEAR: 2026/2027
# 1 MARCH 2026 - 28 FEBRUARY 2027
# ============================================================

TAX_YEAR = "2026/2027"

# UIF
UIF_RATE = Decimal("0.01")
UIF_MONTHLY_CEILING = Decimal("17712.00")


# ============================================================
# TAX REBATES
# ============================================================

PRIMARY_REBATE = Decimal("17820.00")
SECONDARY_REBATE = Decimal("9765.00")
TERTIARY_REBATE = Decimal("3249.00")


# ============================================================
# TAX BRACKETS
# ============================================================

TAX_BRACKETS = [
    {
        "limit": Decimal("245100.00"),
        "base_tax": Decimal("0.00"),
        "rate": Decimal("0.18"),
        "base": Decimal("0.00"),
    },
    {
        "limit": Decimal("383100.00"),
        "base_tax": Decimal("44118.00"),
        "rate": Decimal("0.26"),
        "base": Decimal("245100.00"),
    },
    {
        "limit": Decimal("530200.00"),
        "base_tax": Decimal("79998.00"),
        "rate": Decimal("0.31"),
        "base": Decimal("383100.00"),
    },
    {
        "limit": Decimal("695800.00"),
        "base_tax": Decimal("125599.00"),
        "rate": Decimal("0.36"),
        "base": Decimal("530200.00"),
    },
    {
        "limit": Decimal("887000.00"),
        "base_tax": Decimal("185215.00"),
        "rate": Decimal("0.39"),
        "base": Decimal("695800.00"),
    },
    {
        "limit": Decimal("1878600.00"),
        "base_tax": Decimal("259783.00"),
        "rate": Decimal("0.41"),
        "base": Decimal("887000.00"),
    },
    {
        "limit": None,
        "base_tax": Decimal("666339.00"),
        "rate": Decimal("0.45"),
        "base": Decimal("1878600.00"),
    },
]


# ============================================================
# HELPERS
# ============================================================

def money(value):
    """
    Convert a value to currency with 2 decimal places.
    """
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


# ============================================================
# UIF
# ============================================================

def calculate_employee_uif(monthly_remuneration):
    """
    Calculate employee UIF contribution.

    Employee contribution:
    1% of UIF-liable remuneration,
    subject to the monthly ceiling.
    """

    remuneration = money(monthly_remuneration)

    liable_amount = min(
        remuneration,
        UIF_MONTHLY_CEILING
    )

    return money(
        liable_amount * UIF_RATE
    )


def calculate_employer_uif(monthly_remuneration):
    """
    Calculate employer UIF contribution.
    """

    remuneration = money(monthly_remuneration)

    liable_amount = min(
        remuneration,
        UIF_MONTHLY_CEILING
    )

    return money(
        liable_amount * UIF_RATE
    )


# ============================================================
# ANNUAL TAX BEFORE REBATES
# ============================================================

def calculate_annual_tax_before_rebates(
    annual_taxable_income
):
    """
    Calculate annual individual income tax
    before rebates.
    """

    income = money(annual_taxable_income)

    if income <= 0:
        return Decimal("0.00")

    for bracket in TAX_BRACKETS:

        limit = bracket["limit"]

        if limit is None or income <= limit:

            taxable_above_base = max(
                Decimal("0.00"),
                income - bracket["base"]
            )

            tax = (
                bracket["base_tax"]
                + (
                    taxable_above_base
                    * bracket["rate"]
                )
            )

            return money(tax)

    return Decimal("0.00")


# ============================================================
# TAX REBATE
# ============================================================

def calculate_rebate(age):
    """
    Calculate applicable annual tax rebate.
    """

    age = int(age or 0)

    rebate = PRIMARY_REBATE

    if age >= 75:
        rebate += SECONDARY_REBATE
        rebate += TERTIARY_REBATE

    elif age >= 65:
        rebate += SECONDARY_REBATE

    return money(rebate)


# ============================================================
# ANNUAL PAYE
# ============================================================

def calculate_annual_paye(
    annual_taxable_income,
    age=30
):
    """
    Calculate annual PAYE after applicable rebate.
    """

    annual_tax = calculate_annual_tax_before_rebates(
        annual_taxable_income
    )

    rebate = calculate_rebate(age)

    annual_paye = max(
        Decimal("0.00"),
        annual_tax - rebate
    )

    return money(annual_paye)


# ============================================================
# MONTHLY PAYE
# ============================================================

def calculate_monthly_paye(
    monthly_taxable_income,
    age=30
):
    """
    Simplified monthly PAYE calculation.

    Annualises monthly taxable income,
    calculates annual tax and divides by 12.
    """

    monthly_income = money(
        monthly_taxable_income
    )

    annual_income = (
        monthly_income * Decimal("12")
    )

    annual_paye = calculate_annual_paye(
        annual_income,
        age
    )

    monthly_paye = (
        annual_paye / Decimal("12")
    )

    return money(monthly_paye)


# ============================================================
# COMPLETE PAYROLL CALCULATION
# ============================================================

def calculate_payroll(
    basic_salary,
    overtime=0,
    bonus=0,
    commission=0,
    other_earnings=0,
    other_deductions=0,
    age=30,
):
    """
    Calculate the main payroll values for one employee.
    """

    basic_salary = money(basic_salary)
    overtime = money(overtime)
    bonus = money(bonus)
    commission = money(commission)
    other_earnings = money(other_earnings)
    other_deductions = money(other_deductions)

    # --------------------------------------------------------
    # GROSS PAY
    # --------------------------------------------------------

    gross_pay = (
        basic_salary
        + overtime
        + bonus
        + commission
        + other_earnings
    )

    # --------------------------------------------------------
    # UIF
    # --------------------------------------------------------

    employee_uif = calculate_employee_uif(
        gross_pay
    )

    employer_uif = calculate_employer_uif(
        gross_pay
    )

    # --------------------------------------------------------
    # PAYE
    # --------------------------------------------------------

    paye = calculate_monthly_paye(
        gross_pay,
        age
    )

    # --------------------------------------------------------
    # TOTAL DEDUCTIONS
    # --------------------------------------------------------

    total_deductions = (
        paye
        + employee_uif
        + other_deductions
    )

    # --------------------------------------------------------
    # NET PAY
    # --------------------------------------------------------

    net_pay = max(
        Decimal("0.00"),
        gross_pay - total_deductions
    )

    return {
        "tax_year": TAX_YEAR,

        "basic_salary": basic_salary,
        "overtime": overtime,
        "bonus": bonus,
        "commission": commission,
        "other_earnings": other_earnings,

        "gross_pay": money(gross_pay),

        "paye": money(paye),
        "uif": money(employee_uif),
        "other_deductions": other_deductions,

        "total_deductions": money(
            total_deductions
        ),

        "net_pay": money(net_pay),

        "employer_uif": money(
            employer_uif
        ),
  }
