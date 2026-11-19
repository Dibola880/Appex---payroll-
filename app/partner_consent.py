"""Company-scoped consent governance for controlled partner services."""

import re
from datetime import datetime, timezone

from .models import (
    CompanyIntegration,
    IntegrationProvider,
    PartnerServiceConsent,
    PartnerServiceConsentEvent,
)
from .roles import COMPANY_ADMIN


class PartnerConsentError(ValueError):
    """Consent is missing, invalid, expired, or outside its authorised scope."""


class PartnerConsentPersistenceError(RuntimeError):
    """Consent or audit persistence failed; caller must roll back."""


PURPOSE_BY_OPERATION = {
    "payroll.compliance_summary": "payroll_compliance_reporting",
    "financial_services.product_catalogue": "product_discovery",
}

OPERATION_DATA_CATEGORIES = {
    "payroll.compliance_summary": frozenset({
        "payroll.aggregate_summary",
    }),
    "financial_services.product_catalogue": frozenset(),
    "financial_services.company_offer_request": frozenset({
        "company.reference",
        "financial_services.company_financing_request",
    }),
}

_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$", re.ASCII)
_ALLOWED_CATEGORIES = frozenset().union(*OPERATION_DATA_CATEGORIES.values())

ALLOWED_REVOCATION_REASON_CODES = frozenset({
    "company_request",
    "scope_changed",
    "provider_change",
    "no_longer_required",
})

MAX_CONSENT_EXPIRY_BATCH_SIZE = 500


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PartnerConsentError("%s must be a positive integer." % label)
    return value


def _utc(value, label):
    if not isinstance(value, datetime):
        raise PartnerConsentError("%s must be a datetime." % label)
    if value.utcoffset() is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _now(value=None):
    return datetime.utcnow() if value is None else _utc(value, "Current time")


def _code(value, label):
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise PartnerConsentError("A valid %s is required." % label)
    return value


def _actor_company(actor):
    if actor is None or getattr(actor, "role", None) != COMPANY_ADMIN:
        raise PartnerConsentError("Only a company administrator may manage consent.")
    if getattr(actor, "is_active", None) is not True:
        raise PartnerConsentError("The company administrator is inactive.")

    company_id = _positive_id(
        getattr(actor, "company_id", None), "Actor company ID"
    )
    company = getattr(actor, "company", None)
    if company is None or getattr(company, "id", None) != company_id:
        raise PartnerConsentError("The administrator has no valid company association.")

    actor_id = _positive_id(getattr(actor, "id", None), "Actor user ID")
    return company_id, actor_id


def _load_integration(session, company_id, integration_id):
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
        raise PartnerConsentError("The requested integration is unavailable.")

    integration, provider = row

    if not provider.is_enabled:
        raise PartnerConsentError("The partner provider is disabled.")
    if integration.environment != "sandbox":
        raise PartnerConsentError("Consent is limited to sandbox integrations.")

    if integration.ownership_scope == "company":
        if integration.company_id != company_id:
            raise PartnerConsentError("The integration does not belong to this company.")
    elif integration.ownership_scope == "platform":
        if integration.company_id is not None:
            raise PartnerConsentError("The platform integration has an invalid company assignment.")
    else:
        raise PartnerConsentError("The integration ownership scope is invalid.")

    return integration, provider


def expected_partner_purpose(operation, payload):
    if operation not in OPERATION_DATA_CATEGORIES:
        raise PartnerConsentError("The partner operation is not approved.")

    if operation == "financial_services.company_offer_request":
        return _code(payload.get("purpose_code"), "request purpose code")

    return PURPOSE_BY_OPERATION[operation]


def _categories(values, operation):
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise PartnerConsentError("Data categories must be a collection.")

    if any(not isinstance(value, str) for value in values):
        raise PartnerConsentError("Data categories must contain text values.")

    clean = frozenset(values)
    if len(clean) != len(values):
        raise PartnerConsentError("Duplicate data categories are not permitted.")
    if not clean.issubset(_ALLOWED_CATEGORIES):
        raise PartnerConsentError("A data category is not approved.")
    if clean != OPERATION_DATA_CATEGORIES[operation]:
        raise PartnerConsentError("Categories must exactly match the operation's approved categories.")

    return sorted(clean)


def _event(session, consent, actor_id, event_type, old_status, new_status, reason=None):
    session.add(PartnerServiceConsentEvent(
        consent_id=consent.id,
        company_id=consent.company_id,
        integration_id=consent.integration_id,
        provider_id=consent.provider_id,
        actor_user_id=actor_id,
        event_type=event_type,
        from_status=old_status,
        to_status=new_status,
        reason_code=reason,
    ))


def _flush(session, message):
    try:
        session.flush()
    except Exception:
        raise PartnerConsentPersistenceError(
            message + " Caller must roll back."
        ) from None


def create_pending_partner_service_consent(
    session, *, actor, integration_id, operation, purpose_code,
    data_categories, expires_at, now=None,
):
    """Create a pending company consent. Does not commit."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, actor_id = _actor_company(actor)
    integration_id = _positive_id(integration_id, "Integration ID")

    if operation not in OPERATION_DATA_CATEGORIES:
        raise PartnerConsentError("The partner operation is not approved.")

    purpose_code = _code(purpose_code, "purpose code")
    fixed_purpose = PURPOSE_BY_OPERATION.get(operation)
    if fixed_purpose is not None and purpose_code != fixed_purpose:
        raise PartnerConsentError("The purpose does not match the approved operation purpose.")

    categories = _categories(data_categories, operation)
    current = _now(now)
    expiry = _utc(expires_at, "Consent expiry")
    if expiry <= current:
        raise PartnerConsentError("Consent expiry must be in the future.")

    integration, provider = _load_integration(
        session, company_id, integration_id
    )

    existing = (
        session.query(PartnerServiceConsent)
        .filter_by(
            company_id=company_id,
            integration_id=integration_id,
            provider_code=provider.code,
            operation=operation,
            purpose_code=purpose_code,
            status="active",
        )
        .with_for_update()
        .all()
    )
    if any(_utc(item.expires_at, "Stored expiry") > current for item in existing):
        raise PartnerConsentError("An active consent already exists for this scope and purpose.")

    consent = PartnerServiceConsent(
        company_id=company_id,
        integration_id=integration.id,
        provider_id=provider.id,
        provider_code=provider.code,
        operation=operation,
        purpose_code=purpose_code,
        data_categories=categories,
        status="pending",
        consent_version=1,
        granted_by_user_id=actor_id,
        expires_at=expiry,
        created_at=current,
    )

    try:
        session.add(consent)
        session.flush()
        _event(session, consent, actor_id, "created", None, "pending")
        session.flush()
    except Exception:
        raise PartnerConsentPersistenceError(
            "Consent creation or audit persistence failed. Caller must roll back."
        ) from None

    return consent


def _load_actor_consent(session, actor, consent_id):
    company_id, actor_id = _actor_company(actor)
    consent_id = _positive_id(consent_id, "Consent ID")

    consent = (
        session.query(PartnerServiceConsent)
        .filter(
            PartnerServiceConsent.id == consent_id,
            PartnerServiceConsent.company_id == company_id,
        )
        .with_for_update()
        .first()
    )
    if consent is None or consent.company_id != company_id:
        raise PartnerConsentError("The requested consent is unavailable.")

    return consent, actor_id


def activate_partner_service_consent(session, *, actor, consent_id, now=None):
    """Explicitly activate pending consent."""
    consent, actor_id = _load_actor_consent(session, actor, consent_id)
    current = _now(now)

    if consent.status != "pending":
        raise PartnerConsentError("Only pending consent can be activated.")
    if _utc(consent.expires_at, "Consent expiry") <= current:
        raise PartnerConsentError("Expired consent cannot be activated.")

    consent.status = "active"
    consent.activated_at = current

    try:
        _event(session, consent, actor_id, "activated", "pending", "active")
        _flush(session, "Consent activation or audit persistence failed.")
    except PartnerConsentPersistenceError:
        raise
    except Exception:
        raise PartnerConsentPersistenceError(
            "Consent activation failed. Caller must roll back."
        ) from None

    return consent


def revoke_partner_service_consent(
    session, *, actor, consent_id, reason_code, now=None
):
    """Revoke pending or active consent."""
    consent, actor_id = _load_actor_consent(session, actor, consent_id)
    reason_code = _code(reason_code, "revocation reason code")
    if reason_code not in ALLOWED_REVOCATION_REASON_CODES:
        raise PartnerConsentError("The revocation reason is not approved.")

    if consent.status not in {"pending", "active"}:
        raise PartnerConsentError("Only pending or active consent can be revoked.")

    previous = consent.status
    consent.status = "revoked"
    consent.revoked_by_user_id = actor_id
    consent.revoked_at = _now(now)
    consent.revocation_reason_code = reason_code

    try:
        _event(
            session, consent, actor_id, "revoked",
            previous, "revoked", reason_code,
        )
        _flush(session, "Consent revocation or audit persistence failed.")
    except PartnerConsentPersistenceError:
        raise
    except Exception:
        raise PartnerConsentPersistenceError(
            "Consent revocation failed. Caller must roll back."
        ) from None

    return consent


def expire_partner_service_consent(session, *, consent_id, now=None):
    """Record expiry after the stored expiry time has passed."""
    consent_id = _positive_id(consent_id, "Consent ID")
    consent = (
        session.query(PartnerServiceConsent)
        .filter(PartnerServiceConsent.id == consent_id)
        .with_for_update()
        .first()
    )
    if consent is None:
        raise PartnerConsentError("The requested consent is unavailable.")
    if consent.status not in {"pending", "active"}:
        raise PartnerConsentError("Only pending or active consent can expire.")

    current = _now(now)
    if _utc(consent.expires_at, "Consent expiry") > current:
        raise PartnerConsentError("Consent has not yet expired.")

    previous = consent.status
    consent.status = "expired"

    try:
        _event(session, consent, None, "expired", previous, "expired")
        _flush(session, "Consent expiry or audit persistence failed.")
    except PartnerConsentPersistenceError:
        raise
    except Exception:
        raise PartnerConsentPersistenceError(
            "Consent expiry failed. Caller must roll back."
        ) from None

    return consent


def expire_due_partner_service_consents(
    session, *, now=None, limit=100
):
    """Expire a bounded batch of overdue consents without committing."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_CONSENT_EXPIRY_BATCH_SIZE
    ):
        raise PartnerConsentError(
            "Expiry batch limit must be between 1 and 500."
        )

    current = _now(now)

    rows = (
        session.query(PartnerServiceConsent)
        .filter(
            PartnerServiceConsent.status.in_(("pending", "active")),
            PartnerServiceConsent.expires_at <= current,
        )
        .order_by(
            PartnerServiceConsent.expires_at.asc(),
            PartnerServiceConsent.id.asc(),
        )
        .limit(limit)
        .with_for_update()
        .all()
    )

    expired = []

    try:
        for consent in rows:
            previous = consent.status
            consent.status = "expired"

            _event(
                session,
                consent,
                None,
                "expired",
                previous,
                "expired",
            )
            expired.append(consent)

        if expired:
            _flush(
                session,
                "Consent expiry batch or audit persistence failed.",
            )

    except PartnerConsentPersistenceError:
        raise
    except Exception:
        raise PartnerConsentPersistenceError(
            "Consent expiry batch failed. Caller must roll back."
        ) from None

    return expired


def require_active_partner_service_consent(
    session, *, context, request, now=None
):
    """Require exact company, connection, provider, operation and purpose consent."""
    company_id = _positive_id(context.company_id, "Company ID")
    integration_id = _positive_id(context.integration_id, "Integration ID")
    operation = request.operation
    purpose = expected_partner_purpose(operation, request.payload)
    required = OPERATION_DATA_CATEGORIES[operation]
    current = _now(now)

    rows = (
        session.query(PartnerServiceConsent)
        .filter_by(
            company_id=company_id,
            integration_id=integration_id,
            provider_code=context.provider_code,
            operation=operation,
            purpose_code=purpose,
            status="active",
        )
        .with_for_update()
        .all()
    )

    for consent in rows:
        if _utc(consent.expires_at, "Stored consent expiry") <= current:
            continue
        values = consent.data_categories
        if isinstance(values, (list, tuple, set, frozenset)):
            if frozenset(values) == required:
                return consent

    raise PartnerConsentError(
        "No active, unexpired company consent covers this partner request."
    )


def list_company_partner_service_consents(session, *, actor):
    """List consent records belonging only to the actor's company."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, _ = _actor_company(actor)

    return (
        session.query(PartnerServiceConsent)
        .filter_by(company_id=company_id)
        .order_by(
            PartnerServiceConsent.created_at.desc(),
            PartnerServiceConsent.id.desc(),
        )
        .all()
    )


def list_company_partner_service_consent_events(session, *, actor):
    """List lifecycle events belonging only to the actor's company."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, _ = _actor_company(actor)

    return (
        session.query(PartnerServiceConsentEvent)
        .filter_by(company_id=company_id)
        .order_by(
            PartnerServiceConsentEvent.created_at.desc(),
            PartnerServiceConsentEvent.id.desc(),
        )
        .limit(100)
        .all()
    )
