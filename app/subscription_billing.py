"""Core subscription billing operations.

Transaction ownership remains with the caller:
these functions flush but never commit or silently roll back.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func

from . import db
from .models import (
    SubscriptionInvoice,
    SubscriptionInvoiceItem,
    SubscriptionPayment,
)


CENT = Decimal("0.01")
ZERO = Decimal("0.00")

INVOICE_DRAFT = "Draft"
INVOICE_ISSUED = "Issued"
INVOICE_PARTIALLY_PAID = "Partially Paid"
INVOICE_PAID = "Paid"
INVOICE_OVERDUE = "Overdue"
INVOICE_VOID = "Void"

PAYMENT_PENDING = "Pending"
PAYMENT_VERIFIED = "Verified"
PAYMENT_FAILED = "Failed"
PAYMENT_REFUNDED = "Refunded"


class BillingError(ValueError):
    """Raised when a billing operation violates a business rule."""


def _money(value, field_name="amount"):
    try:
        result = Decimal(str(value)).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError):
        raise BillingError(f"Invalid {field_name}.") from None

    if not result.is_finite():
        raise BillingError(f"Invalid {field_name}.")

    return result


def _positive_quantity(value):
    try:
        result = Decimal(str(value)).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError):
        raise BillingError("Invalid invoice item quantity.") from None

    if not result.is_finite() or result <= 0:
        raise BillingError("Invoice item quantity must be positive.")

    return result


def _require_company_subscription(company, subscription):
    if company is None or subscription is None:
        raise BillingError("Company and subscription are required.")

    if subscription.company_id != company.id:
        raise BillingError(
            "The subscription does not belong to this company."
        )


def _get_invoice(invoice_or_id, lock=True):
    if isinstance(invoice_or_id, SubscriptionInvoice):
        invoice_id = invoice_or_id.id
    else:
        invoice_id = invoice_or_id

    if invoice_id is None:
        raise BillingError("A saved invoice is required.")

    query = SubscriptionInvoice.query.filter_by(id=invoice_id)

    if lock:
        query = query.with_for_update()

    invoice = query.first()

    if invoice is None:
        raise BillingError("Invoice not found.")

    return invoice


def create_draft_invoice(
    company,
    subscription,
    invoice_number,
    items,
    tax_amount=0,
    due_at=None,
    period_start=None,
    period_end=None,
):
    """Create a draft invoice with immutable-intent line-item snapshots.

    Each item must contain:
      description, quantity, unit_price
    Optional:
      plan_id

    The caller must commit the transaction.
    """
    _require_company_subscription(company, subscription)

    if not invoice_number or not isinstance(invoice_number, str):
        raise BillingError("Invoice number is required.")

    invoice_number = invoice_number.strip()

    if not invoice_number or len(invoice_number) > 64:
        raise BillingError("Invoice number must be 1–64 characters.")

    if not isinstance(items, (list, tuple)) or not items:
        raise BillingError("At least one invoice item is required.")

    tax = _money(tax_amount, "tax amount")

    if tax < ZERO:
        raise BillingError("Tax amount cannot be negative.")

    invoice = SubscriptionInvoice(
        company_id=company.id,
        subscription_id=subscription.id,
        invoice_number=invoice_number,
        status=INVOICE_DRAFT,
        currency=subscription.currency or "ZAR",
        subtotal=ZERO,
        tax_amount=tax,
        total=ZERO,
        amount_paid=ZERO,
        balance_due=ZERO,
        due_at=due_at,
        period_start=period_start,
        period_end=period_end,
    )

    subtotal = ZERO

    for item_data in items:
        if not isinstance(item_data, dict):
            raise BillingError("Each invoice item must be an object.")

        description = item_data.get("description")

        if not isinstance(description, str):
            raise BillingError("Invoice item description is required.")

        description = description.strip()

        if not description or len(description) > 255:
            raise BillingError(
                "Invoice item description must be 1–255 characters."
            )

        quantity = _positive_quantity(item_data.get("quantity", 1))
        unit_price = _money(
            item_data.get("unit_price"),
            "invoice item unit price",
        )

        if unit_price < ZERO:
            raise BillingError("Unit price cannot be negative.")

        line_total = (quantity * unit_price).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )

        plan_id = item_data.get("plan_id")

        invoice.items.append(
            SubscriptionInvoiceItem(
                plan_id=plan_id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

        subtotal += line_total

    subtotal = subtotal.quantize(CENT, rounding=ROUND_HALF_UP)
    total = (subtotal + tax).quantize(CENT, rounding=ROUND_HALF_UP)

    invoice.subtotal = subtotal
    invoice.total = total
    invoice.balance_due = total

    db.session.add(invoice)
    db.session.flush()

    return invoice


def issue_invoice(invoice_or_id, now=None):
    """Issue a draft invoice and freeze its financial snapshot."""
    invoice = _get_invoice(invoice_or_id)

    if invoice.status != INVOICE_DRAFT:
        raise BillingError("Only draft invoices can be issued.")

    if not invoice.items:
        raise BillingError("An invoice without items cannot be issued.")

    if invoice.total != invoice.subtotal + invoice.tax_amount:
        raise BillingError("Invoice totals do not reconcile.")

    invoice.issued_at = now or datetime.utcnow()
    invoice.status = INVOICE_ISSUED
    invoice.amount_paid = ZERO
    invoice.balance_due = invoice.total
    invoice.updated_at = invoice.issued_at

    db.session.flush()
    return invoice


def void_invoice(invoice_or_id, now=None):
    """Void an unpaid invoice without deleting its history."""
    invoice = _get_invoice(invoice_or_id)

    if invoice.status not in (INVOICE_DRAFT, INVOICE_ISSUED):
        raise BillingError("This invoice cannot be voided.")

    if _money(invoice.amount_paid) != ZERO:
        raise BillingError("An invoice with payments cannot be voided.")

    pending_count = SubscriptionPayment.query.filter_by(
        invoice_id=invoice.id,
        status=PAYMENT_PENDING,
    ).count()

    if pending_count:
        raise BillingError(
            "Resolve pending payments before voiding this invoice."
        )

    invoice.status = INVOICE_VOID
    invoice.updated_at = now or datetime.utcnow()

    db.session.flush()
    return invoice


def register_pending_payment(
    invoice_or_id,
    company,
    amount,
    idempotency_key,
    payment_provider=None,
    provider_payment_id=None,
):
    """Record a pending payment. This does not verify or apply payment."""
    invoice = _get_invoice(invoice_or_id)

    if company is None or invoice.company_id != company.id:
        raise BillingError("Invoice does not belong to this company.")

    if invoice.status not in (
        INVOICE_ISSUED,
        INVOICE_PARTIALLY_PAID,
        INVOICE_OVERDUE,
    ):
        raise BillingError("This invoice cannot accept payments.")

    payment_amount = _money(amount, "payment amount")

    if payment_amount <= ZERO:
        raise BillingError("Payment amount must be greater than zero.")

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise BillingError("An idempotency key is required.")

    idempotency_key = idempotency_key.strip()

    if len(idempotency_key) > 200:
        raise BillingError("Idempotency key is too long.")

    existing = SubscriptionPayment.query.filter_by(
        idempotency_key=idempotency_key
    ).first()

    if existing is not None:
        same_request = (
            existing.invoice_id == invoice.id
            and existing.company_id == company.id
            and _money(existing.amount) == payment_amount
            and existing.currency == invoice.currency
        )

        if not same_request:
            raise BillingError(
                "This idempotency key was already used for another request."
            )

        return existing

    pending_total = (
        db.session.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0))
        .filter(
            SubscriptionPayment.invoice_id == invoice.id,
            SubscriptionPayment.status == PAYMENT_PENDING,
        )
        .scalar()
    )

    available_balance = (
        _money(invoice.balance_due) - _money(pending_total)
    )

    if payment_amount > available_balance:
        raise BillingError(
            "Pending payments would exceed the invoice balance."
        )

    payment = SubscriptionPayment(
        invoice_id=invoice.id,
        company_id=company.id,
        amount=payment_amount,
        currency=invoice.currency,
        status=PAYMENT_PENDING,
        payment_provider=payment_provider,
        provider_payment_id=provider_payment_id,
        idempotency_key=idempotency_key,
    )

    db.session.add(payment)
    db.session.flush()

    return payment


def reconcile_verified_payment(payment_or_id, now=None):
    """Apply a payment already verified by a trusted process.

    This function deliberately cannot change Pending to Verified.
    A trusted verifier must first set status='Verified' and verified_at.
    """
    if isinstance(payment_or_id, SubscriptionPayment):
        payment_id = payment_or_id.id
    else:
        payment_id = payment_or_id

    if payment_id is None:
        raise BillingError("A saved payment is required.")

    payment = (
        SubscriptionPayment.query
        .filter_by(id=payment_id)
        .with_for_update()
        .first()
    )

    if payment is None:
        raise BillingError("Payment not found.")

    if payment.status != PAYMENT_VERIFIED or payment.verified_at is None:
        raise BillingError(
            "Only payments verified by a trusted process can be reconciled."
        )

    invoice = _get_invoice(payment.invoice_id)

    if invoice.company_id != payment.company_id:
        raise BillingError("Payment and invoice company do not match.")

    if payment.currency != invoice.currency:
        raise BillingError("Payment and invoice currencies do not match.")

    if invoice.status == INVOICE_VOID:
        raise BillingError("A void invoice cannot receive a payment.")

    verified_total = (
        db.session.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0))
        .filter(
            SubscriptionPayment.invoice_id == invoice.id,
            SubscriptionPayment.status == PAYMENT_VERIFIED,
        )
        .scalar()
    )

    verified_total = _money(verified_total)

    if verified_total > _money(invoice.total):
        raise BillingError(
            "Verified payments exceed the invoice total. Manual review required."
        )

    invoice.amount_paid = verified_total
    invoice.balance_due = _money(invoice.total) - verified_total

    timestamp = now or datetime.utcnow()

    if invoice.balance_due == ZERO:
        invoice.status = INVOICE_PAID
    elif invoice.due_at is not None and invoice.due_at <= timestamp:
        invoice.status = INVOICE_OVERDUE
    elif verified_total > ZERO:
        invoice.status = INVOICE_PARTIALLY_PAID
    else:
        invoice.status = INVOICE_ISSUED

    invoice.updated_at = timestamp

    db.session.flush()

    return invoice
