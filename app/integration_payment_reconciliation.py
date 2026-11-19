"""Provider-neutral reconciliation of trusted subscription payment notices."""

from dataclasses import dataclass
from datetime import datetime, timezone

from . import db
from .models import PaymentReconciliation, SubscriptionPayment
from .payment_verification import (
    PaymentVerificationError,
    verify_subscription_payment_notice,
)
from .subscription_billing import (
    BillingError,
    reconcile_verified_payment,
)


class PaymentReconciliationTransactionError(RuntimeError):
    """The caller must roll back after an unexpected reconciliation failure."""


@dataclass(frozen=True)
class PaymentReconciliationOutcome:
    outcome: str
    reason_code: str = None
    reconciliation_id: int = None


def _timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise ValueError("A valid reconciliation timestamp is required.")
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _record(
    *,
    event,
    event_context,
    notice,
    outcome,
    reason_code=None,
    payment=None,
    invoice=None,
    timestamp,
):
    record = PaymentReconciliation(
        event_id=event.id,
        integration_id=event.integration_id,
        provider_id=event.provider_id,
        company_id=payment.company_id if payment is not None else event.company_id,
        invoice_id=invoice.id if invoice is not None else (
            payment.invoice_id if payment is not None else None
        ),
        payment_id=payment.id if payment is not None else None,
        provider_payment_id=notice.provider_payment_id,
        amount=notice.amount,
        currency=notice.currency,
        outcome=outcome,
        reason_code=reason_code,
        attempted_at=timestamp,
        reconciled_at=timestamp if outcome == "reconciled" else None,
    )
    db.session.add(record)
    db.session.flush()

    return PaymentReconciliationOutcome(
        outcome=outcome,
        reason_code=reason_code,
        reconciliation_id=record.id,
    )


def reconcile_payment_notice(
    event,
    event_context,
    notice,
    *,
    now=None,
):
    """Verify and reconcile a trusted notice within the caller's transaction.

    This function never commits or rolls back.
    It never treats a provider reference alone as proof of payment.
    """
    from .integration_adapters import (
        PaymentVerificationNotice,
        WebhookEventContext,
    )

    if type(event_context) is not WebhookEventContext:
        raise ValueError("A verified webhook context is required.")

    if type(notice) is not PaymentVerificationNotice:
        raise ValueError("A trusted payment notice is required.")

    if (
        event is None
        or event.id is None
        or event.integration_id != event_context.integration_id
        or event.provider_id is None
        or event.provider is None
        or event.provider.code != event_context.provider_code
        or event.integration is None
        or event.integration.provider_id != event.provider_id
        or event.integration.company_id != event.company_id
        or event.integration.ownership_scope not in {'platform', 'company'}
        or (
            event.integration.ownership_scope == 'platform'
            and event.company_id is not None
        )
        or (
            event.integration.ownership_scope == 'company'
            and event.company_id is None
        )
        or event.external_event_id != event_context.external_event_id
        or event.event_type != event_context.event_type
        or event.company_id != event_context.company_id
        or event.verified_at is None
        or event_context.verified_at is None
    ):
        raise ValueError("The event and verified context do not match.")

    timestamp = _timestamp(now)

    # One durable reconciliation result per integration event.
    existing_event_record = (
        PaymentReconciliation.query
        .filter_by(event_id=event.id)
        .first()
    )
    if existing_event_record is not None:
        return PaymentReconciliationOutcome(
            outcome=existing_event_record.outcome,
            reason_code=existing_event_record.reason_code,
            reconciliation_id=existing_event_record.id,
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
        return _record(
            event=event,
            event_context=event_context,
            notice=notice,
            outcome="unmatched",
            reason_code="payment_not_found",
            timestamp=timestamp,
        )

    if (
        event_context.company_id is not None
        and payment.company_id != event_context.company_id
    ):
        return _record(
            event=event,
            event_context=event_context,
            notice=notice,
            outcome="mismatch",
            reason_code="company_mismatch",
            # Do not expose another company's payment or invoice IDs.
            # _record will use the event's own company_id.
            timestamp=timestamp,
        )

    previous_success = (
        PaymentReconciliation.query
        .filter_by(payment_id=payment.id, outcome="reconciled")
        .first()
    )
    if previous_success is not None:
        return _record(
            event=event,
            event_context=event_context,
            notice=notice,
            outcome="duplicate",
            reason_code="payment_already_reconciled",
            payment=payment,
            timestamp=timestamp,
        )

    try:
        verified_payment = verify_subscription_payment_notice(
            event_context,
            notice,
            now=timestamp,
        )
    except PaymentVerificationError:
        # Do not expose provider or internal exception text in history.
        return _record(
            event=event,
            event_context=event_context,
            notice=notice,
            outcome="mismatch",
            reason_code="payment_verification_rejected",
            payment=payment,
            timestamp=timestamp,
        )
    except Exception as exc:
        raise PaymentReconciliationTransactionError(
            "Unexpected payment verification failure; caller must roll back."
        ) from exc

    try:
        invoice = reconcile_verified_payment(
            verified_payment,
            now=timestamp,
        )
    except BillingError as exc:
        raise PaymentReconciliationTransactionError(
            "Verified payment could not be reconciled; caller must roll back."
        ) from exc
    except Exception as exc:
        raise PaymentReconciliationTransactionError(
            "Unexpected invoice reconciliation failure; caller must roll back."
        ) from exc

    try:
        return _record(
            event=event,
            event_context=event_context,
            notice=notice,
            outcome="reconciled",
            payment=verified_payment,
            invoice=invoice,
            timestamp=timestamp,
        )
    except Exception as exc:
        raise PaymentReconciliationTransactionError(
            "Reconciliation history could not be saved; caller must roll back."
        ) from exc
