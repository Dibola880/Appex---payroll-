"""Central role identifiers for Appex Payroll authorization."""

PLATFORM_SUPER_ADMIN = "platform_super_admin"
COMPANY_ADMIN = "company_admin"
EMPLOYER = "employer"
EMPLOYEE = "employee"
LEGACY_ADMIN = "admin"

# Existing employer and legacy-admin role semantics are preserved.
EMPLOYER_ROLES = frozenset({
    EMPLOYER,
    LEGACY_ADMIN,
})

# Company administrators receive the same company-scoped operational
# access as employers. Platform-wide administration remains separate.
COMPANY_OPERATIONAL_ROLES = frozenset({
    EMPLOYER,
    LEGACY_ADMIN,
    COMPANY_ADMIN,
})

COMPANY_ADMIN_ROLES = frozenset({
    COMPANY_ADMIN,
})

ALL_ROLES = frozenset({
    PLATFORM_SUPER_ADMIN,
    COMPANY_ADMIN,
    EMPLOYER,
    EMPLOYEE,
    LEGACY_ADMIN,
})
