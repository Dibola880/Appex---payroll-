"""Trusted provider-to-billing payment verification.

Only a successful result from an explicitly registered adapter should
supply a PaymentVerificationNotice to this service.

Transaction ownership remains with the caller. This module never commits
or silently rolls back.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from . import db
from .integration_adapters import WebhookEventContext
from .models import SubscriptionInvoice, SubscriptionPayment
from .payment_verification_contract import PaymentVerificationNotice


CENT = Decimal("0.01")
PAYMENT_PENDING = "Pending"
PAYMENT_VERIFIED = "Verified"
INVOICE_VOID = "Void"

ALLOWED_PAYMENT_INVOICE_STATUSES = {
    "Issued",
    "Partially Paid",
    "Overdue",
}
MAX_PAYMENT_AMOUNT = Decimal("9999999999.99")


class PaymentVerificationError(ValueError):
    """Raised when a trusted payment notice fails billing validation."""


def verify_subscription_payment_notice(event_context, notice, now=None):
    """Verify an adapter-produced notice against one pending billing payment.

    The caller must pass the notice returned by the successful registered
    adapter result. This function locks the payment and invoice, validates
    ownership and amounts, checks the existing verified total, then marks
    the matching pending payment Verified.

    Invoice reconciliation remains a separate billing operation.
    """

    if type(event_context) is not WebhookEventContext:
        raise PaymentVerificationError(
            "A verified webhook event context is required."
        )

    if type(notice) is not PaymentVerificationNotice:
        raise PaymentVerificationError(
            "A trusted adapter payment notice is required."
        )

    if event_context.verified_at is None:
        raise PaymentVerificationError(
            "The webhook event has not been verified."
        )

    payment = (
        SubscriptionPayment.query
        .filter_by(
            payment_provider=event_context.provider_code,
            provider_payment_id=notice.provider_payment_id,
        )
        .with_for_update()
        .first()
    )

    if payment is None:
        raise PaymentVerificationError(
            "No matching provider payment was found."
        )

    if (
        event_context.company_id is not None
        and payment.company_id != event_context.company_id
    ):
        raise PaymentVerificationError(
            "Payment does not belong to the event company."
        )

    if Decimal(str(payment.amount)) != notice.amount:
        raise PaymentVerificationError("Payment amount mismatch.")

    if payment.currency != notice.currency:
        raise PaymentVerificationError("Payment currency mismatch.")

    invoice = (
        SubscriptionInvoice.query
        .filter_by(id=payment.invoice_id)
        .with_for_update()
        .first()
    )

    if invoice is None:
        raise PaymentVerificationError("Payment invoice not found.")

    if invoice.company_id != payment.company_id:
        raise PaymentVerificationError(
            "Payment and invoice company do not match."
        )

    if invoice.currency != payment.currency:
        raise PaymentVerificationError(
            "Payment and invoice currencies do not match."
        )

    if invoice.status not in ALLOWED_PAYMENT_INVOICE_STATUSES:
        raise PaymentVerificationError(
            "Invoice is not eligible for payment verification."
        )

    # A repeated event is handled by webhook event idempotency. A different
    # event must not use an already-verified payment as fresh proof.
    if payment.status == PAYMENT_VERIFIED:
        raise PaymentVerificationError(
            "Payment is already verified; manual reconciliation may be required."
        )

    if payment.status != PAYMENT_PENDING:
        raise PaymentVerificationError(
            "Only pending payments can be verified."
        )

    verified_total = (
        db.session.query(
            func.coalesce(func.sum(SubscriptionPayment.amount), 0)
        )
        .filter(
            SubscriptionPayment.invoice_id == invoice.id,
            SubscriptionPayment.status == PAYMENT_VERIFIED,
        )
        .scalar()
    )

    verified_total = Decimal(str(verified_total or 0))
    proposed_total = verified_total + notice.amount
    invoice_total = Decimal(str(invoice.total))

    if (
        not proposed_total.is_finite()
        or proposed_total > MAX_PAYMENT_AMOUNT
        or proposed_total > invoice_total
    ):
        raise PaymentVerificationError(
            "Payment would exceed the remaining invoice balance."
        )

    timestamp = now or datetime.now(timezone.utc).replace(tzinfo=None)

    if not isinstance(timestamp, datetime):
        raise PaymentVerificationError("Invalid verification timestamp.")

    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)

    payment.status = PAYMENT_VERIFIED
    payment.verified_at = timestamp
    payment.updated_at = timestamp

    db.session.flush()
    return payment
