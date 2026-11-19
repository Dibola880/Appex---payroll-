"""Trusted provider connection verification.

The caller owns the transaction. This service flushes but never commits
or silently rolls back.
"""

from datetime import datetime

from . import db
from .integration_adapters import (
    ConnectionVerificationResult,
    DEFAULT_ADAPTER_REGISTRY,
    IntegrationAdapterError,
    IntegrationAdapterUnavailable,
)
from .integration_security import (
    IntegrationCredentialError,
    decrypt_credentials,
)
from .models import CompanyIntegration


class IntegrationConnectionVerificationError(ValueError):
    """Raised when a connection cannot safely be verified."""


def _validate_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntegrationConnectionVerificationError(
            "A valid %s is required." % label
        )


def _get_connection(
    integration_id,
    *,
    ownership_scope,
    company_id=None,
):
    _validate_id(integration_id, "integration ID")

    query = CompanyIntegration.query.filter_by(
        id=integration_id,
        ownership_scope=ownership_scope,
    )

    if ownership_scope == "company":
        _validate_id(company_id, "company ID")
        query = query.filter_by(company_id=company_id)
    else:
        query = query.filter(
            CompanyIntegration.company_id.is_(None)
        )

    integration = query.first()

    if integration is None:
        raise IntegrationConnectionVerificationError(
            "Integration connection was not found."
        )

    return integration


def _record_failure(integration, error_code):
    """Record only a fixed or validated safe error code."""
    integration.status = "error"
    integration.last_error_at = datetime.utcnow()
    integration.last_error_code = error_code
    integration.updated_at = datetime.utcnow()

    db.session.flush()

    return integration


def _verify_connection(integration, registry):
    if integration.status == "disabled":
        raise IntegrationConnectionVerificationError(
            "Disabled connections cannot be verified."
        )

    provider = integration.provider

    if provider is None or not provider.is_enabled:
        raise IntegrationConnectionVerificationError(
            "The integration provider is not enabled."
        )

    # Resolve the adapter before decrypting credentials. An unimplemented
    # provider must not cause unnecessary access to credential material.
    try:
        adapter = registry.get(provider.code)
    except IntegrationAdapterUnavailable:
        raise IntegrationConnectionVerificationError(
            "No approved adapter is available for this provider."
        ) from None

    # Catalogue declarations must be supported by the registered adapter.
    # This check happens before credentials are decrypted or provider code runs.
    try:
        registry.validate_capabilities(
            provider.code,
            provider.capabilities,
        )
    except IntegrationAdapterUnavailable:
        raise IntegrationConnectionVerificationError(
            "No approved adapter is available for this provider."
        ) from None
    except IntegrationAdapterError:
        return _record_failure(
            integration,
            "provider_capabilities_unsupported",
        )

    if not integration.credentials_encrypted:
        return _record_failure(
            integration,
            "credentials_missing",
        )

    try:
        credentials = decrypt_credentials(
            integration.credentials_encrypted,
            integration.credential_key_version,
        )
    except IntegrationCredentialError:
        return _record_failure(
            integration,
            "credentials_unavailable",
        )

    configuration = dict(integration.configuration or {})

    try:
        result = adapter.verify_connection(
            configuration=configuration,
            credentials=credentials,
        )
    except Exception:
        # Never persist exception text, provider responses, or secrets.
        return _record_failure(
            integration,
            "adapter_verification_failed",
        )

    if not isinstance(result, ConnectionVerificationResult):
        return _record_failure(
            integration,
            "adapter_invalid_result",
        )

    if not result.success:
        return _record_failure(
            integration,
            result.error_code,
        )

    # This is the only path that can establish connected status.
    integration.status = "connected"
    integration.last_connected_at = datetime.utcnow()
    integration.last_error_at = None
    integration.last_error_code = None
    integration.updated_at = datetime.utcnow()

    db.session.flush()

    return integration


def verify_company_integration_connection(
    company_id,
    integration_id,
    *,
    registry=DEFAULT_ADAPTER_REGISTRY,
):
    """Verify only a connection belonging to the specified company."""
    integration = _get_connection(
        integration_id,
        ownership_scope="company",
        company_id=company_id,
    )

    return _verify_connection(integration, registry)


def verify_platform_integration_connection(
    integration_id,
    *,
    registry=DEFAULT_ADAPTER_REGISTRY,
):
    """Verify only a platform-owned connection."""
    integration = _get_connection(
        integration_id,
        ownership_scope="platform",
    )

    return _verify_connection(integration, registry)
