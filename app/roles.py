"""Central role identifiers for Appex Payroll authorization."""

PLATFORM_SUPER_ADMIN = "platform_super_admin"
COMPANY_ADMIN = "company_admin"
EMPLOYER = "employer"
EMPLOYEE = "employee"
LEGACY_ADMIN = "admin"

# Existing employer access is preserved during this milestone.
# Company administrators are deliberately excluded until route-level
# company ownership checks have been reviewed.
EMPLOYER_ROLES = frozenset({
    EMPLOYER,
    LEGACY_ADMIN,
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
