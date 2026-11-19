"""Verified, idempotent webhook event recording.

This module never commits or rolls back the caller's outer transaction.
Raw webhook bodies and decrypted credentials are never persisted.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from . import db
from .models import (
    CompanyIntegration,
    IntegrationEvent,
    IntegrationProvider,
)
from .integration_adapters import (
    DEFAULT_ADAPTER_REGISTRY,
    IntegrationAdapterError,
    IntegrationAdapterRegistry,
    IntegrationAdapterUnavailable,
)
from .webhook_security import (
    DEFAULT_TOLERANCE_SECONDS,
    WebhookSecurityError,
    verify_integration_webhook,
)


MAX_WEBHOOK_BODY_BYTES = 1024 * 1024
MAX_EVENT_ID_LENGTH = 200
MAX_EVENT_TYPE_LENGTH = 120

# Only fully connected integrations may submit normal business events.
# Pending connections require a separate provider-specific verification flow.
ALLOWED_CONNECTION_STATUSES = frozenset({
    "connected",
})

ALLOWED_METADATA_KEYS = frozenset({
    "delivery_id",
    "api_version",
    "resource_type",
    "livemode",
})


class IntegrationWebhookError(ValueError):
    """Raised when a webhook cannot safely be recorded."""


def _validate_text(value, label, maximum):
    if not isinstance(value, str):
        raise IntegrationWebhookError(
            f"A valid {label} is required."
        )

    if not value or value != value.strip():
        raise IntegrationWebhookError(
            f"A valid {label} is required."
        )

    if len(value) > maximum:
        raise IntegrationWebhookError(
            f"The {label} is too long."
        )

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise IntegrationWebhookError(
            f"The {label} contains invalid characters."
        )

    return value


def _validate_metadata(metadata):
    if metadata is None:
        return {}

    if not isinstance(metadata, dict):
        raise IntegrationWebhookError(
            "Webhook metadata must be an object."
        )

    result = {}

    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or key not in ALLOWED_METADATA_KEYS
        ):
            raise IntegrationWebhookError(
                "Webhook metadata contains an unsupported field."
            )

        if isinstance(value, bool):
            result[key] = value
            continue

        if isinstance(value, int):
            if value < -(2 ** 63) or value > (2 ** 63) - 1:
                raise IntegrationWebhookError(
                    "Webhook metadata contains an out-of-range integer."
                )
            result[key] = value
            continue

        if isinstance(value, str):
            if len(value) > 200 or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            ):
                raise IntegrationWebhookError(
                    "Webhook metadata contains an invalid value."
                )
            result[key] = value
            continue

        raise IntegrationWebhookError(
            "Webhook metadata contains an unsupported value."
        )

    return result


def _validate_integration_id(integration_id):
    if (
        isinstance(integration_id, bool)
        or not isinstance(integration_id, int)
        or integration_id <= 0
    ):
        raise IntegrationWebhookError(
            "A valid integration ID is required."
        )


def _ensure_clean_session(session):
    """Prevent ingestion from flushing unrelated caller-owned changes."""
    if (
        session.new
        or session.deleted
        or any(
            session.is_modified(obj, include_collections=True)
            for obj in session.dirty
        )
    ):
        raise IntegrationWebhookError(
            "Webhook ingestion requires a clean database session."
        )


def _existing_event(integration_id, external_event_id):
    return IntegrationEvent.query.filter_by(
        integration_id=integration_id,
        external_event_id=external_event_id,
    ).first()


def _resolve_connection(integration_id):
    integration = (
        CompanyIntegration.query
        .join(
            IntegrationProvider,
            IntegrationProvider.id == CompanyIntegration.provider_id,
        )
        .filter(
            CompanyIntegration.id == integration_id,
            IntegrationProvider.is_enabled.is_(True),
        )
        .first()
    )

    if integration is None:
        raise IntegrationWebhookError(
            "Integration is unavailable or its provider is disabled."
        )

    if integration.status not in ALLOWED_CONNECTION_STATUSES:
        raise IntegrationWebhookError(
            "Integration connection is not accepting webhook events."
        )

    return integration


def record_verified_webhook_event(
    *,
    integration_id,
    raw_body,
    signature,
    timestamp,
    metadata=None,
    now=None,
    tolerance_seconds=DEFAULT_TOLERANCE_SECONDS,
    adapter_registry=None,
):
    """Verify, parse and record one provider webhook event.

    Signature verification always precedes provider-specific parsing.
    Event identity is derived only from the authenticated raw body.
    The caller retains ownership of the outer database transaction.
    """
    _validate_integration_id(integration_id)

    if not isinstance(raw_body, bytes):
        raise IntegrationWebhookError(
            "Webhook body must be raw bytes."
        )

    if not raw_body:
        raise IntegrationWebhookError(
            "Webhook body must not be empty."
        )

    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise IntegrationWebhookError(
            "Webhook body exceeds the permitted size."
        )

    safe_metadata = _validate_metadata(metadata)

    if adapter_registry is None:
        adapter_registry = DEFAULT_ADAPTER_REGISTRY
    elif not isinstance(adapter_registry, IntegrationAdapterRegistry):
        raise IntegrationWebhookError(
            "Webhook adapter registry is invalid."
        )

    # Check before ORM queries, which can autoflush caller changes.
    _ensure_clean_session(db.session())

    integration = _resolve_connection(integration_id)

    # Authenticate the exact raw body before parsing it.
    try:
        provider_timestamp = verify_integration_webhook(
            integration=integration,
            raw_body=raw_body,
            signature=signature,
            timestamp=timestamp,
            now=now,
            tolerance_seconds=tolerance_seconds,
        )
    except WebhookSecurityError:
        raise IntegrationWebhookError(
            "Webhook authenticity or timestamp validation failed."
        ) from None

    try:
        identity = adapter_registry.parse_webhook_event(
            integration.provider.code,
            raw_body=raw_body,
        )
    except IntegrationAdapterUnavailable:
        raise IntegrationWebhookError(
            "No approved webhook adapter is available for this provider."
        ) from None
    except IntegrationAdapterError:
        raise IntegrationWebhookError(
            "Provider webhook payload could not be safely parsed."
        ) from None

    external_event_id = _validate_text(
        identity.external_event_id,
        "external event ID",
        MAX_EVENT_ID_LENGTH,
    )
    event_type = _validate_text(
        identity.event_type,
        "event type",
        MAX_EVENT_TYPE_LENGTH,
    )

    payload_hash = hashlib.sha256(raw_body).hexdigest()

    existing = _existing_event(
        integration.id,
        external_event_id,
    )

    if existing is not None:
        if (
            existing.payload_hash != payload_hash
            or existing.event_type != event_type
        ):
            raise IntegrationWebhookError(
                "Webhook event ID conflicts with a previously recorded event."
            )
        return existing, False

    verified_at = datetime.now(timezone.utc).replace(tzinfo=None)

    event = IntegrationEvent(
        provider_id=integration.provider_id,
        integration_id=integration.id,
        company_id=integration.company_id,
        external_event_id=external_event_id,
        event_type=event_type,
        status="verified",
        payload_hash=payload_hash,
        metadata_json=safe_metadata,
        received_at=verified_at,
        provider_timestamp=provider_timestamp,
        verified_at=verified_at,
    )

    try:
        with db.session.begin_nested():
            db.session.add(event)
            db.session.flush()
    except IntegrityError:
        existing = _existing_event(
            integration.id,
            external_event_id,
        )

        if existing is None:
            raise IntegrationWebhookError(
                "Webhook event could not be recorded."
            ) from None

        if (
            existing.payload_hash != payload_hash
            or existing.event_type != event_type
        ):
            raise IntegrationWebhookError(
                "Webhook event ID conflicts with a previously recorded event."
            ) from None

        return existing, False

    return event, True
