"""Reusable standard chart-of-accounts definitions.

These are templates only. Importing this module does not create
or modify company accounts and performs no database operations.
"""

STANDARD_ACCOUNTS = (
    {
        "account_code": "1000",
        "system_code": "ASSETS",
        "name": "Assets",
        "account_type": "asset",
        "normal_balance": "debit",
        "parent_code": None,
        "allow_manual_posting": False,
    },
    {
        "account_code": "1010",
        "system_code": "BANK",
        "name": "Bank",
        "account_type": "asset",
        "normal_balance": "debit",
        "parent_code": "1000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "1020",
        "system_code": "CASH",
        "name": "Cash",
        "account_type": "asset",
        "normal_balance": "debit",
        "parent_code": "1000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "1100",
        "system_code": "ACCOUNTS_RECEIVABLE",
        "name": "Accounts Receivable",
        "account_type": "asset",
        "normal_balance": "debit",
        "parent_code": "1000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "1200",
        "system_code": "EQUIPMENT",
        "name": "Equipment",
        "account_type": "asset",
        "normal_balance": "debit",
        "parent_code": "1000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2000",
        "system_code": "LIABILITIES",
        "name": "Liabilities",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": None,
        "allow_manual_posting": False,
    },
    {
        "account_code": "2010",
        "system_code": "ACCOUNTS_PAYABLE",
        "name": "Accounts Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2100",
        "system_code": "PAYE_PAYABLE",
        "name": "PAYE Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2110",
        "system_code": "UIF_PAYABLE",
        "name": "UIF Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2120",
        "system_code": "OTHER_PAYROLL_DEDUCTIONS",
        "name": "Other Payroll Deductions Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2130",
        "system_code": "NET_SALARIES_PAYABLE",
        "name": "Net Salaries Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "2200",
        "system_code": "LOANS_PAYABLE",
        "name": "Loans Payable",
        "account_type": "liability",
        "normal_balance": "credit",
        "parent_code": "2000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "3000",
        "system_code": "EQUITY",
        "name": "Equity",
        "account_type": "equity",
        "normal_balance": "credit",
        "parent_code": None,
        "allow_manual_posting": False,
    },
    {
        "account_code": "3010",
        "system_code": "OWNER_CAPITAL",
        "name": "Owner Capital",
        "account_type": "equity",
        "normal_balance": "credit",
        "parent_code": "3000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "3100",
        "system_code": "RETAINED_EARNINGS",
        "name": "Retained Earnings",
        "account_type": "equity",
        "normal_balance": "credit",
        "parent_code": "3000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "3200",
        "system_code": "CURRENT_YEAR_EARNINGS",
        "name": "Current Year Earnings",
        "account_type": "equity",
        "normal_balance": "credit",
        "parent_code": "3000",
        "allow_manual_posting": False,
    },
    {
        "account_code": "4000",
        "system_code": "INCOME",
        "name": "Income",
        "account_type": "income",
        "normal_balance": "credit",
        "parent_code": None,
        "allow_manual_posting": False,
    },
    {
        "account_code": "4010",
        "system_code": "SALES_REVENUE",
        "name": "Sales Revenue",
        "account_type": "income",
        "normal_balance": "credit",
        "parent_code": "4000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "4020",
        "system_code": "SERVICE_REVENUE",
        "name": "Service Revenue",
        "account_type": "income",
        "normal_balance": "credit",
        "parent_code": "4000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "4100",
        "system_code": "OTHER_INCOME",
        "name": "Other Income",
        "account_type": "income",
        "normal_balance": "credit",
        "parent_code": "4000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "5000",
        "system_code": "EXPENSES",
        "name": "Expenses",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": None,
        "allow_manual_posting": False,
    },
    {
        "account_code": "5010",
        "system_code": "SALARIES_WAGES",
        "name": "Salaries and Wages",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": "5000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "5020",
        "system_code": "EMPLOYER_UIF",
        "name": "Employer UIF Expense",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": "5000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "5030",
        "system_code": "OPERATING_EXPENSES",
        "name": "Operating Expenses",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": "5000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "5040",
        "system_code": "RENT_EXPENSE",
        "name": "Rent Expense",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": "5000",
        "allow_manual_posting": True,
    },
    {
        "account_code": "5050",
        "system_code": "BANK_CHARGES",
        "name": "Bank Charges",
        "account_type": "expense",
        "normal_balance": "debit",
        "parent_code": "5000",
        "allow_manual_posting": True,
    },
)


def validate_standard_accounts(accounts=STANDARD_ACCOUNTS):
    """Validate standard account templates without database access."""

    required_fields = {
        "account_code",
        "system_code",
        "name",
        "account_type",
        "normal_balance",
        "parent_code",
        "allow_manual_posting",
    }

    if not isinstance(accounts, (list, tuple)) or not accounts:
        raise ValueError("Account templates must be a non-empty list or tuple.")

    codes = set()
    system_codes = set()
    by_code = {}

    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("Each account template must be a dictionary.")

        if set(account) != required_fields:
            raise ValueError("Account template has missing or extra fields.")

        for field in ("account_code", "system_code", "name"):
            value = account[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid or empty account field: {field}.")

        code = account["account_code"]
        system_code = account["system_code"]
        account_type = account["account_type"]
        normal_balance = account["normal_balance"]
        parent_code = account["parent_code"]

        if not isinstance(account_type, str) or account_type not in {
            "asset", "liability", "equity", "income", "expense"
        }:
            raise ValueError(f"Invalid account type: {code}")

        if not isinstance(normal_balance, str):
            raise ValueError(f"Invalid normal balance: {code}")

        expected_balance = (
            "debit"
            if account_type in {"asset", "expense"}
            else "credit"
        )

        if normal_balance != expected_balance:
            raise ValueError(f"Invalid normal balance: {code}")

        if parent_code is not None and (
            not isinstance(parent_code, str) or not parent_code.strip()
        ):
            raise ValueError(f"Invalid parent code: {code}")

        if type(account["allow_manual_posting"]) is not bool:
            raise ValueError(
                f"allow_manual_posting must be boolean: {code}"
            )

        if code in codes or system_code in system_codes:
            raise ValueError("Duplicate account code or system code.")

        codes.add(code)
        system_codes.add(system_code)
        by_code[code] = account

    for account in accounts:
        parent_code = account["parent_code"]

        if parent_code is None:
            continue

        parent = by_code.get(parent_code)

        if parent is None:
            raise ValueError(
                f"Missing parent {parent_code} for {account['account_code']}"
            )

        if parent["account_type"] != account["account_type"]:
            raise ValueError(
                f"Parent account type mismatch: {account['account_code']}"
            )

        if parent["parent_code"] is not None:
            raise ValueError(
                "Standard template currently supports one parent level: "
                f"{account['account_code']}"
            )

    return True


def prepare_company_accounts(company_id, existing_accounts=()):
    """
    Prepare standard account dictionaries for one company.

    This function performs no database operations and creates no records.
    Existing accounts must already be scoped to the requested company.
    Parent relationships remain expressed as parent_code for later resolution.
    """
    if (
        isinstance(company_id, bool)
        or not isinstance(company_id, int)
        or company_id <= 0
    ):
        raise ValueError("company_id must be a positive integer.")

    validate_standard_accounts()

    def read_value(account, field):
        if not isinstance(account, dict):
            raise ValueError(
                "Existing accounts must be plain dictionaries."
            )
        return account.get(field)

    existing_codes = set()
    existing_system_codes = set()

    for account in existing_accounts:
        existing_company_id = read_value(account, "company_id")

        if existing_company_id != company_id:
            raise ValueError(
                "Existing account belongs to a different company."
            )

        code = read_value(account, "account_code")
        system_code = read_value(account, "system_code")

        if not isinstance(code, str) or not code.strip():
            raise ValueError("Existing account has an invalid account code.")

        if code in existing_codes:
            raise ValueError(f"Duplicate existing account code: {code}")

        existing_codes.add(code)

        if system_code is not None:
            if not isinstance(system_code, str) or not system_code.strip():
                raise ValueError("Existing account has an invalid system code.")

            if system_code in existing_system_codes:
                raise ValueError(
                    f"Duplicate existing system code: {system_code}"
                )

            existing_system_codes.add(system_code)

    prepared = []

    for template in STANDARD_ACCOUNTS:
        code = template["account_code"]
        system_code = template["system_code"]

        if code in existing_codes:
            raise ValueError(
                f"Account code already exists for company {company_id}: {code}"
            )

        if system_code in existing_system_codes:
            raise ValueError(
                f"System code already exists for company {company_id}: "
                f"{system_code}"
            )

        account_data = dict(template)
        account_data["company_id"] = company_id
        prepared.append(account_data)

    return prepared
