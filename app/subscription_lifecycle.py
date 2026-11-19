"""
Subscription lifecycle operations.

This module does not verify payments or activate paid subscriptions.
A payment-provider reference is never treated as proof of payment.

Functions mutate ORM objects but leave transaction commit/rollback to callers.
"""

from datetime import datetime, timezone

from . import db
from .models import CompanySubscription


ACCESSIBLE_STATUSES = frozenset({"trial", "active"})


def _utc_naive(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def subscription_period_end(subscription):
    """Return the effective end date for a subscription, if known."""
    status = (subscription.status or "").strip().lower()

    if status == "trial" and subscription.trial_ends_at is not None:
        return _utc_naive(subscription.trial_ends_at)

    if subscription.current_period_end is not None:
        return _utc_naive(subscription.current_period_end)

    # A trial without trial_ends_at is not safe to expire automatically.
    return None


def request_subscription_cancellation(company, now=None):
    """
    Schedule cancellation at the existing period end.

    Access remains available until the effective period end. This function
    never changes the subscription status to Cancelled immediately.
    """
    if company is None or not getattr(company, "id", None):
        raise ValueError("A valid company is required.")

    subscription = (
        CompanySubscription.query
        .filter_by(company_id=company.id, is_current=True)
        .first()
    )

    if subscription is None:
        raise ValueError("There is no current subscription to cancel.")

    status = (subscription.status or "").strip().lower()
    if status not in ACCESSIBLE_STATUSES:
        raise ValueError("Only an active or trial subscription can be cancelled.")

    if subscription.cancel_at_period_end:
        return subscription

    current_time = _utc_naive(now)
    period_end = subscription_period_end(subscription)

    if period_end is None:
        raise ValueError(
            "The subscription has no recorded period end. "
            "Cancellation cannot be scheduled safely."
        )

    if period_end <= current_time:
        raise ValueError(
            "The subscription period has already ended. "
            "Process its expiry instead."
        )

    subscription.cancel_at_period_end = True
    subscription.cancelled_at = current_time
    subscription.updated_at = current_time

    return subscription


def expire_due_subscriptions(now=None, company_id=None):
    """
    Close current subscriptions whose recorded trial/billing period has ended.

    Returns the number expired. The caller owns the transaction.
    No renewal or payment activation is attempted.
    """
    current_time = _utc_naive(now)

    query = CompanySubscription.query.filter_by(is_current=True)

    if company_id is not None:
        query = query.filter_by(company_id=company_id)

    expired_count = 0

    for subscription in query.order_by(CompanySubscription.id.asc()).all():
        status = (subscription.status or "").strip().lower()

        if status not in ACCESSIBLE_STATUSES:
            continue

        period_end = subscription_period_end(subscription)

        if period_end is None or period_end > current_time:
            continue

        subscription.status = "Expired"
        subscription.is_current = False
        subscription.ended_at = period_end
        subscription.updated_at = current_time

        company = subscription.company
        if company is not None:
            company.subscription_plan = (
                subscription.plan.name if subscription.plan else company.subscription_plan
            )
            company.subscription_status = "Expired"

        expired_count += 1

    return expired_count
