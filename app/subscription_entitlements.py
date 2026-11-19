"""
Central subscription entitlement resolution.

This module is read-only: it does not modify subscriptions, companies,
plans, payment records, or database schema.

Feature configuration format:

{
    "features": {
        "payroll": True,
        "accounting": False,
        "invoicing": True
    }
}
"""

from datetime import datetime, timezone

from .models import CompanySubscription


FREE_TRIAL_DAYS = 30


ACCESSIBLE_SUBSCRIPTION_STATUSES = frozenset({
    "trial",
    "active",
})


def _utc_naive(value=None):
    """Return a UTC datetime compatible with existing naive DB timestamps."""
    value = value or datetime.now(timezone.utc)

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def get_current_subscription(company):
    """
    Return the company's current subscription, or None.

    Historical subscription records are never selected.
    """
    if company is None or not getattr(company, "id", None):
        return None

    return (
        CompanySubscription.query
        .filter_by(
            company_id=company.id,
            is_current=True,
        )
        .first()
    )


def get_company_entitlements(company, now=None):
    """
    Resolve a read-only entitlement snapshot for a company.

    Legacy companies without subscription records retain their legacy
    plan/status information, but receive no invented feature grants.
    """
    legacy_plan = getattr(company, "subscription_plan", None)
    legacy_status = getattr(company, "subscription_status", None)

    subscription = get_current_subscription(company)

    result = {
        "source": "legacy",
        "has_subscription": False,
        "is_access_active": False,
        "plan_code": None,
        "plan_name": legacy_plan,
        "subscription_status": legacy_status,
        "billing_interval": None,
        "currency": None,
        "amount": None,
        "employee_limit": None,
        "features": {},
    }

    if subscription is None:
        return result

    plan = subscription.plan

    result.update({
        "source": "subscription",
        "has_subscription": True,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.name if plan else None,
        "subscription_status": subscription.status,
        "billing_interval": subscription.billing_interval,
        "currency": subscription.currency,
        "amount": subscription.amount,
        "employee_limit": plan.employee_limit if plan else None,
    })

    if plan is None:
        return result

    current_time = _utc_naive(now)
    status = (subscription.status or "").strip().lower()

    access_active = (
        bool(plan.is_active)
        and status in ACCESSIBLE_SUBSCRIPTION_STATUSES
    )

    if (
        access_active
        and subscription.trial_ends_at is not None
        and subscription.trial_ends_at <= current_time
    ):
        access_active = False

    if (
        access_active
        and subscription.current_period_end is not None
        and subscription.current_period_end <= current_time
    ):
        access_active = False

    result["is_access_active"] = access_active

    # Never expose feature grants for inactive subscriptions.
    if access_active:
        configuration = plan.feature_config

        if isinstance(configuration, dict):
            configured_features = configuration.get("features", {})

            if isinstance(configured_features, dict):
                result["features"] = {
                    key: value
                    for key, value in configured_features.items()
                    if isinstance(key, str) and isinstance(value, bool)
                }

    return result


def has_feature(company, feature_code, now=None):
    """
    Return True only when an active subscription explicitly grants a feature.

    Missing, malformed, inactive, and legacy entitlements default to False.
    """
    if not isinstance(feature_code, str) or not feature_code.strip():
        return False

    entitlements = get_company_entitlements(company, now=now)

    if not entitlements["is_access_active"]:
        return False

    return entitlements["features"].get(feature_code.strip(), False)
