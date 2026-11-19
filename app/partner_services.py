"""Tenant-safe orchestration for controlled partner-service preparation."""

from dataclasses import dataclass
import hmac
import re

from .partner_payload_security import (
    PartnerPayloadEncryptionError,
    decrypt_partner_payload,
    partner_payload_sha256,
)
from .models import (
    CompanyIntegration,
    IntegrationProvider,
    PartnerServiceAuditLog,
)
from .integration_adapters.partner import (
    PartnerServiceContext,
    PartnerServiceRequest,
)
from .partner_consent import (
    PartnerConsentError,
    require_active_partner_service_consent,
)
from .partner_request_reviews import (
    PartnerRequestReviewError,
    require_approved_partner_service_request_review,
    mark_partner_service_request_review_prepared,
    mark_partner_service_request_review_preparation_rejected,
)
from .integration_adapters.partner_registry import (
    DEFAULT_PARTNER_SERVICE_REGISTRY,
    PartnerServiceAdapterRegistry,
    PartnerServiceAuditRecord,
    PartnerServiceRegistryError,
    build_partner_service_audit_record,
)


class PartnerServiceRequestError(ValueError):
    """Raised when a partner request fails application-level validation."""


class PartnerServiceAuditPersistenceError(RuntimeError):
    """Audit persistence failed; caller must roll back."""


@dataclass(frozen=True)
class PartnerServicePreparation:
    result: object
    audit_record: PartnerServiceAuditRecord


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PartnerServiceRequestError(
            "%s must be a positive integer." % label
        )
    return value


def prepare_partner_service_request(
    session,
    *,
    company_id,
    integration_id,
    request,
    registry=None,
    actor_user_id=None,
    now=None,
):
    """Validate tenant ownership and prepare an approved partner request.

    This function does not commit, roll back, send money, or make network calls.
    """
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id = _positive_id(company_id, "Company ID")
    integration_id = _positive_id(integration_id, "Integration ID")

    if type(request) is not PartnerServiceRequest:
        raise TypeError("A validated partner service request is required.")

    if actor_user_id is not None:
        actor_user_id = _positive_id(actor_user_id, "Actor user ID")

    if registry is None:
        registry = DEFAULT_PARTNER_SERVICE_REGISTRY

    if not isinstance(registry, PartnerServiceAdapterRegistry):
        raise TypeError("A valid partner service registry is required.")

    row = (
        session.query(CompanyIntegration, IntegrationProvider)
        .join(
            IntegrationProvider,
            IntegrationProvider.id == CompanyIntegration.provider_id,
        )
        .filter(CompanyIntegration.id == integration_id)
        .with_for_update()
        .first()
    )

    if row is None:
        raise PartnerServiceRequestError(
            "The requested integration is unavailable."
        )

    integration, provider = row

    if not provider.is_enabled:
        raise PartnerServiceRequestError(
            "The partner provider is disabled."
        )

    if integration.status != "connected":
        raise PartnerServiceRequestError(
            "The partner integration is not connected."
        )

    if integration.environment != "sandbox":
        raise PartnerServiceRequestError(
            "Only sandbox partner integrations are permitted in this phase."
        )

    if integration.ownership_scope == "company":
        if integration.company_id != company_id:
            raise PartnerServiceRequestError(
                "The integration does not belong to this company."
            )
    elif integration.ownership_scope == "platform":
        if integration.company_id is not None:
            raise PartnerServiceRequestError(
                "The platform integration has an invalid company assignment."
            )
    else:
        raise PartnerServiceRequestError(
            "The integration ownership scope is invalid."
        )

    capabilities = provider.capabilities

    if not isinstance(capabilities, (list, tuple, set, frozenset)):
        raise PartnerServiceRequestError(
            "The provider catalogue capabilities are invalid."
        )

    existing_audit = (
        session.query(PartnerServiceAuditLog)
        .filter_by(
            integration_id=integration_id,
            request_id=request.request_id,
        )
        .with_for_update()
        .first()
    )

    if existing_audit is not None:
        raise PartnerServiceRequestError(
            "This partner request ID has already been processed."
        )

    context = PartnerServiceContext(
        company_id=company_id,
        integration_id=integration.id,
        provider_code=provider.code,
        environment=integration.environment,
        ownership_scope=integration.ownership_scope,
        integration_company_id=integration.company_id,
    )

    try:
        review = require_approved_partner_service_request_review(
            session,
            context=context,
            request=request,
            provider_id=provider.id,
            now=now,
        )
    except PartnerRequestReviewError as exc:
        raise PartnerServiceRequestError(
            "Independent company approval is required for this partner request."
        ) from exc

    # The approved review snapshot, never the caller payload, is authoritative.
    if (
        not review.encrypted_payload
        or not review.payload_key_version
        or review.payload_snapshot_erased_at is not None
        or not isinstance(review.payload_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", review.payload_hash) is None
    ):
        raise PartnerServiceRequestError(
            "The approved partner request has no usable payload snapshot."
        )

    try:
        stored_payload = decrypt_partner_payload(
            review.encrypted_payload,
            review.payload_key_version,
        )
        stored_request = PartnerServiceRequest(
            request_id=review.request_id,
            operation=review.operation,
            payload=stored_payload,
        )
        stored_hash = partner_payload_sha256(
            dict(stored_request.payload)
        )
    except (PartnerPayloadEncryptionError, ValueError):
        raise PartnerServiceRequestError(
            "The approved partner payload could not be verified."
        ) from None

    if not hmac.compare_digest(stored_hash, review.payload_hash):
        raise PartnerServiceRequestError(
            "The approved partner payload failed integrity verification."
        )

    if stored_request.request_id != request.request_id:
        raise PartnerServiceRequestError(
            "The approved partner request identity does not match."
        )

    if stored_request.operation not in capabilities:
        raise PartnerServiceRequestError(
            "The provider catalogue does not approve this operation."
        )

    try:
        require_active_partner_service_consent(
            session,
            context=context,
            request=stored_request,
            now=now,
        )
    except PartnerConsentError:
        raise PartnerServiceRequestError(
            "Active company consent is required for this partner request."
        ) from None

    configuration = integration.configuration or {}

    try:
        result = registry.prepare_request(
            provider.code,
            context=context,
            request=stored_request,
            provider_capabilities=capabilities,
            configuration=configuration,
        )
    except PartnerServiceRegistryError as exc:
        raise PartnerServiceRequestError(
            "Partner request preparation was not available."
        ) from exc

    audit_record = build_partner_service_audit_record(
        context=context,
        request=stored_request,
        result=result,
        now=now,
    )

    persisted_audit = PartnerServiceAuditLog(
        company_id=audit_record.company_id,
        integration_id=audit_record.integration_id,
        provider_id=provider.id,
        request_id=audit_record.request_id,
        provider_code=audit_record.provider_code,
        operation=audit_record.operation,
        payload_hash=audit_record.payload_hash,
        outcome=audit_record.outcome,
        error_code=audit_record.error_code,
        partner_reference=audit_record.partner_reference,
        created_at=audit_record.occurred_at,
    )

    try:
        session.add(persisted_audit)
        session.flush()
    except Exception:
        raise PartnerServiceAuditPersistenceError(
            "Partner audit persistence failed. Caller must roll back."
        ) from None

    try:
        if result.accepted:
            mark_partner_service_request_review_prepared(
                session,
                review=review,
                actor_user_id=actor_user_id,
                now=now,
            )
        else:
            mark_partner_service_request_review_preparation_rejected(
                session,
                review=review,
                reason_code=result.error_code,
                actor_user_id=actor_user_id,
                now=now,
            )
    except PartnerRequestReviewError as exc:
        raise PartnerServiceAuditPersistenceError(
            "Partner review completion failed. Caller must roll back."
        ) from exc

    return PartnerServicePreparation(
        result=result,
        audit_record=audit_record,
    )
