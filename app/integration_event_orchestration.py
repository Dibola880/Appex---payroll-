"""Orchestration for processing claimed integration webhook events.

The caller must commit the event claim before invoking this service.
This service never commits or rolls back and never stores credentials,
raw webhook bodies, or provider exception text.
"""

from dataclasses import dataclass

from . import db
from .integration_adapters import (
    DEFAULT_ADAPTER_REGISTRY,
    IntegrationAdapter,
    IntegrationAdapterError,
    IntegrationAdapterRegistry,
    IntegrationAdapterUnavailable,
    WebhookEventContext,
)
from .integration_event_processing import (
    _utc_naive,
    _validate_event_id,
    _validate_token,
    complete_integration_event,
    fail_integration_event,
)
from .integration_security import (
    IntegrationCredentialError,
    decrypt_credentials,
)
from .models import IntegrationEvent


from .integration_payment_reconciliation import (
    PaymentReconciliationTransactionError,
    reconcile_payment_notice,
)


@dataclass(frozen=True)
class IntegrationEventProcessingOutcome:
    """Safe result of an orchestration attempt."""

    status: str
    error_code: str = None

class PaymentVerificationTransactionError(RuntimeError):
    """The caller must roll back after a payment transaction error.

    This service never rolls back automatically. The original exception,
    when present, is preserved as the cause.
    """



def _failed_outcome(event_id, claim_token, error_code):
    """Record a safe failure only while the claim remains valid."""
    updated = fail_integration_event(
        event_id,
        claim_token=claim_token,
        error_code=error_code,
    )

    if not updated:
        return IntegrationEventProcessingOutcome(
            status="claim_lost",
        )

    return IntegrationEventProcessingOutcome(
        status="failed",
        error_code=error_code,
    )


def process_claimed_integration_event(
    event_id,
    *,
    claim_token,
    registry=DEFAULT_ADAPTER_REGISTRY,
    now=None,
):
    """Process an event only while the supplied claim is current.

    The caller must commit the claim transaction before calling this
    function. The caller retains ownership of this function's transaction.

    No provider network activity is initiated by this orchestration layer.
    Only explicitly registered adapter implementations are invoked.
    """
    _validate_event_id(event_id)
    _validate_token(claim_token)

    if not isinstance(registry, IntegrationAdapterRegistry):
        raise ValueError("A valid integration adapter registry is required.")

    started_at = _utc_naive(now)

    # Refresh existing ORM state so a previous in-session claim update
    # cannot leave us relying on stale event attributes.
    event = (
        IntegrationEvent.query
        .populate_existing()
        .filter(
            IntegrationEvent.id == event_id,
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_token == claim_token,
            IntegrationEvent.processing_lease_expires_at.is_not(None),
            IntegrationEvent.processing_lease_expires_at > started_at,
        )
        .first()
    )

    if event is None:
        return IntegrationEventProcessingOutcome(
            status="claim_unavailable",
        )

    integration = event.integration
    provider = event.provider

    if integration is None or provider is None:
        return _failed_outcome(
            event_id,
            claim_token,
            "event_connection_unavailable",
        )

    # Ensure the persisted event still belongs to this exact connection
    # and provider, including the company/platform ownership boundary.
    if (
        integration.id != event.integration_id
        or integration.provider_id != event.provider_id
        or integration.company_id != event.company_id
        or integration.ownership_scope not in {"platform", "company"}
        or (
            integration.ownership_scope == "platform"
            and integration.company_id is not None
        )
        or (
            integration.ownership_scope == "company"
            and integration.company_id is None
        )
    ):
        return _failed_outcome(
            event_id,
            claim_token,
            "event_connection_mismatch",
        )

    if not provider.is_enabled:
        return _failed_outcome(
            event_id,
            claim_token,
            "provider_disabled",
        )

    if integration.status != "connected":
        return _failed_outcome(
            event_id,
            claim_token,
            "integration_not_connected",
        )

    configuration = integration.configuration or {}

    if not isinstance(configuration, dict):
        return _failed_outcome(
            event_id,
            claim_token,
            "integration_configuration_invalid",
        )

    # Validate the catalogue's declared capabilities before accessing
    # encrypted credentials.
    try:
        registry.validate_capabilities(
            provider.code,
            provider.capabilities,
        )
    except IntegrationAdapterUnavailable:
        return _failed_outcome(
            event_id,
            claim_token,
            "adapter_unavailable",
        )
    except IntegrationAdapterError:
        return _failed_outcome(
            event_id,
            claim_token,
            "provider_capabilities_unsupported",
        )

    try:
        adapter = registry.get(provider.code)
    except IntegrationAdapterUnavailable:
        return _failed_outcome(
            event_id,
            claim_token,
            "adapter_unavailable",
        )

    # Do not decrypt credentials for connection-only adapters.
    if (
        getattr(type(adapter), "process_webhook_event", None)
        is IntegrationAdapter.process_webhook_event
    ):
        return _failed_outcome(
            event_id,
            claim_token,
            "adapter_processing_unavailable",
        )

    if not integration.credentials_encrypted:
        return _failed_outcome(
            event_id,
            claim_token,
            "credentials_missing",
        )

    try:
        credentials = decrypt_credentials(
            integration.credentials_encrypted,
            integration.credential_key_version,
        )
    except IntegrationCredentialError:
        return _failed_outcome(
            event_id,
            claim_token,
            "credentials_unavailable",
        )

    # Construct a safe context. Raw webhook bodies and ORM objects are
    # deliberately excluded from the adapter contract.
    try:
        event_context = WebhookEventContext(
            integration_id=event.integration_id,
            provider_code=provider.code,
            external_event_id=event.external_event_id,
            event_type=event.event_type,
            company_id=event.company_id,
            payload_hash=event.payload_hash,
            metadata=event.metadata_json or {},
            provider_timestamp=event.provider_timestamp,
            verified_at=event.verified_at,
        )
    except (TypeError, ValueError):
        return _failed_outcome(
            event_id,
            claim_token,
            "event_context_invalid",
        )

    try:
        result = registry.process_webhook_event(
            provider.code,
            event=event_context,
            configuration=dict(configuration),
            credentials=credentials,
        )
    except IntegrationAdapterUnavailable:
        return _failed_outcome(
            event_id,
            claim_token,
            "adapter_unavailable",
        )
    except IntegrationAdapterError:
        return _failed_outcome(
            event_id,
            claim_token,
            "adapter_processing_failed",
        )

    if not result.success:
        return _failed_outcome(
            event_id,
            claim_token,
            result.error_code,
        )

    # Payment verification and event completion share the caller's transaction.
    has_payment_notice = result.payment_notice is not None

    if has_payment_notice:
        try:
            reconciliation = reconcile_payment_notice(
                event,
                event_context,
                result.payment_notice,
                now=started_at,
            )
        except PaymentReconciliationTransactionError as exc:
            raise PaymentVerificationTransactionError(
                "Payment reconciliation failed; the caller must roll back."
            ) from exc
        except (TypeError, ValueError):
            return _failed_outcome(
                event_id,
                claim_token,
                "payment_reconciliation_input_invalid",
            )

    try:
        completed = complete_integration_event(
            event_id,
            claim_token=claim_token,
        )
    except Exception as exc:
        if has_payment_notice:
            raise PaymentVerificationTransactionError(
                "Event completion failed after payment verification; "
                "the caller must roll back the transaction."
            ) from exc
        raise

    if not completed:
        if has_payment_notice:
            raise PaymentVerificationTransactionError(
                "Payment verification requires transaction rollback: "
                "event claim lost."
            )
        return IntegrationEventProcessingOutcome(
            status="claim_lost",
        )

    return IntegrationEventProcessingOutcome(
        status="processed",
    )
