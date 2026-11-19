"""Independent company-admin review for controlled partner-service requests."""

import re
from datetime import datetime, timedelta, timezone

from .models import (
    CompanyIntegration,
    IntegrationProvider,
    PartnerServiceRequestReview,
    PartnerServiceRequestReviewEvent,
)
from .integration_adapters.partner import PartnerServiceRequest
from .roles import COMPANY_ADMIN
from .partner_payload_security import (
    encrypt_partner_payload,
    partner_payload_sha256,
    PartnerPayloadEncryptionError,
)


class PartnerRequestReviewError(ValueError):
    """Raised when a partner request review cannot proceed."""


REJECTION_REASON_CODES = frozenset({
    "insufficient_information",
    "outside_company_policy",
    "incorrect_request",
    "not_authorised",
    "other",
})


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PartnerRequestReviewError(
            "%s must be a positive integer." % label
        )
    return value


def _now(value=None):
    current = datetime.utcnow() if value is None else value
    if not isinstance(current, datetime):
        raise TypeError("Review time must be a datetime.")
    if current.utcoffset() is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def _set_terminal_timestamps(review, current):
    """Set immutable terminal and provisional retention timestamps once."""
    terminal_at = getattr(review, "terminal_at", None)
    retention_until = getattr(review, "payload_retention_until", None)

    if terminal_at is not None or retention_until is not None:
        raise PartnerRequestReviewError(
            "Terminal retention timestamps are already populated or inconsistent."
        )

    try:
        retention_until = current.replace(year=current.year + 7)
    except ValueError:
        # A 29 February terminal date maps to 28 February seven years later.
        if current.month != 2 or current.day != 29:
            raise
        retention_until = current.replace(
            year=current.year + 7,
            month=2,
            day=28,
        )

    review.terminal_at = current
    review.payload_retention_until = retention_until


def _actor_company(actor):
    if actor is None or getattr(actor, "role", None) != COMPANY_ADMIN:
        raise PartnerRequestReviewError(
            "Only a company administrator may manage partner request reviews."
        )
    if getattr(actor, "is_active", None) is not True:
        raise PartnerRequestReviewError(
            "The company administrator is inactive."
        )

    company_id = _positive_id(
        getattr(actor, "company_id", None), "Actor company ID"
    )
    company = getattr(actor, "company", None)
    if company is None or getattr(company, "id", None) != company_id:
        raise PartnerRequestReviewError(
            "The administrator has no valid company association."
        )

    actor_id = _positive_id(getattr(actor, "id", None), "Actor user ID")
    return company_id, actor_id


def partner_request_payload_hash(request):
    if type(request) is not PartnerServiceRequest:
        raise TypeError("A validated partner service request is required.")

    return partner_payload_sha256(dict(request.payload))


def _record_event(
    session, *, review, actor_user_id, event_type,
    from_status, to_status, reason_code=None
):
    session.add(
        PartnerServiceRequestReviewEvent(
            review_id=review.id,
            company_id=review.company_id,
            integration_id=review.integration_id,
            provider_id=review.provider_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            reason_code=reason_code,
        )
    )


def _expire_review(session, review, current, actor_user_id=None):
    """Record expiry without taking ownership of the caller's transaction."""
    previous_status = review.status
    if previous_status not in ("pending", "approved"):
        return review

    _set_terminal_timestamps(review, current)
    review.status = "expired"
    try:
        _record_event(
            session,
            review=review,
            actor_user_id=actor_user_id,
            event_type="expired",
            from_status=previous_status,
            to_status="expired",
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review expiry persistence failed. Caller must roll back."
        ) from None

    return review


def _load_company_integration(session, company_id, integration_id):
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
        raise PartnerRequestReviewError(
            "The requested integration is unavailable."
        )

    integration, provider = row

    if not provider.is_enabled:
        raise PartnerRequestReviewError("The partner provider is disabled.")
    if integration.status != "connected":
        raise PartnerRequestReviewError(
            "The partner integration is not connected."
        )
    if integration.environment != "sandbox":
        raise PartnerRequestReviewError(
            "Only sandbox partner integrations are permitted."
        )

    if integration.ownership_scope == "company":
        if integration.company_id != company_id:
            raise PartnerRequestReviewError(
                "The integration does not belong to this company."
            )
    elif integration.ownership_scope == "platform":
        if integration.company_id is not None:
            raise PartnerRequestReviewError(
                "The platform integration has an invalid company assignment."
            )
    else:
        raise PartnerRequestReviewError(
            "The integration ownership scope is invalid."
        )

    return integration, provider


def submit_partner_service_request_review(
    session, *, actor, integration_id, request, now=None
):
    """Submit a validated request for independent review; never invokes an adapter."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, actor_id = _actor_company(actor)
    integration_id = _positive_id(integration_id, "Integration ID")

    if type(request) is not PartnerServiceRequest:
        raise TypeError("A validated partner service request is required.")

    current = _now(now)
    integration, provider = _load_company_integration(
        session, company_id, integration_id
    )

    capabilities = provider.capabilities
    if not isinstance(capabilities, (list, tuple, set, frozenset)):
        raise PartnerRequestReviewError(
            "The provider catalogue capabilities are invalid."
        )
    if request.operation not in capabilities:
        raise PartnerRequestReviewError(
            "The provider catalogue does not approve this operation."
        )

    existing = (
        session.query(PartnerServiceRequestReview)
        .filter_by(
            integration_id=integration_id,
            request_id=request.request_id,
        )
        .with_for_update()
        .first()
    )
    if existing is not None:
        raise PartnerRequestReviewError(
            "A review already exists for this integration and request ID."
        )

    try:
        encrypted_payload, payload_key_version, payload_hash = (
            encrypt_partner_payload(dict(request.payload))
        )
    except PartnerPayloadEncryptionError:
        raise PartnerRequestReviewError(
            "Partner payload encryption is unavailable. Review submission was refused."
        ) from None

    review = PartnerServiceRequestReview(
        company_id=company_id,
        integration_id=integration.id,
        provider_id=provider.id,
        request_id=request.request_id,
        provider_code=provider.code,
        operation=request.operation,
        encrypted_payload=encrypted_payload,
        payload_key_version=payload_key_version,
        payload_hash=payload_hash,
        status="pending",
        requested_by_user_id=actor_id,
        submitted_at=current,
        expires_at=current + timedelta(hours=24),
    )

    try:
        session.add(review)
        session.flush()
        _record_event(
            session,
            review=review,
            actor_user_id=actor_id,
            event_type="submitted",
            from_status=None,
            to_status="pending",
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review submission persistence failed. Caller must roll back."
        ) from None

    return review


def _load_company_review(session, *, company_id, review_id):
    review = (
        session.query(PartnerServiceRequestReview)
        .filter_by(id=review_id, company_id=company_id)
        .with_for_update()
        .first()
    )
    if review is None:
        raise PartnerRequestReviewError(
            "The partner request review is unavailable."
        )
    return review


def approve_partner_service_request_review(
    session, *, actor, review_id, now=None
):
    """Approve a pending request by a different active company administrator."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, actor_id = _actor_company(actor)
    review_id = _positive_id(review_id, "Review ID")
    current = _now(now)
    review = _load_company_review(
        session, company_id=company_id, review_id=review_id
    )

    if review.requested_by_user_id == actor_id:
        raise PartnerRequestReviewError(
            "The requester cannot approve their own partner request."
        )
    if review.status != "pending":
        raise PartnerRequestReviewError(
            "Only pending partner requests can be approved."
        )
    if review.expires_at <= current:
        _expire_review(session, review, current, actor_user_id=actor_id)
        return review

    review.status = "approved"
    review.reviewed_by_user_id = actor_id
    review.reviewed_at = current

    try:
        _record_event(
            session,
            review=review,
            actor_user_id=actor_id,
            event_type="approved",
            from_status="pending",
            to_status="approved",
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review approval persistence failed. Caller must roll back."
        ) from None

    return review


def reject_partner_service_request_review(
    session, *, actor, review_id, reason_code, now=None
):
    """Reject a pending partner request with a controlled reason code."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, actor_id = _actor_company(actor)
    review_id = _positive_id(review_id, "Review ID")
    current = _now(now)

    if (
        not isinstance(reason_code, str)
        or reason_code not in REJECTION_REASON_CODES
    ):
        raise PartnerRequestReviewError("Invalid review rejection reason.")

    review = _load_company_review(
        session, company_id=company_id, review_id=review_id
    )

    if review.requested_by_user_id == actor_id:
        raise PartnerRequestReviewError(
            "The requester cannot reject their own partner request."
        )
    if review.status != "pending":
        raise PartnerRequestReviewError(
            "Only pending partner requests can be rejected."
        )
    if review.expires_at <= current:
        _expire_review(session, review, current, actor_user_id=actor_id)
        return review

    _set_terminal_timestamps(review, current)
    review.status = "rejected"
    review.reviewed_by_user_id = actor_id
    review.reviewed_at = current
    review.rejection_reason_code = reason_code

    try:
        _record_event(
            session,
            review=review,
            actor_user_id=actor_id,
            event_type="rejected",
            from_status="pending",
            to_status="rejected",
            reason_code=reason_code,
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review rejection persistence failed. Caller must roll back."
        ) from None

    return review


def require_approved_partner_service_request_review(
    session, *, context, request, provider_id, now=None
):
    """Lock and validate the exact approved review before adapter preparation."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    current = _now(now)
    provider_id = _positive_id(provider_id, "Provider ID")
    review = (
        session.query(PartnerServiceRequestReview)
        .filter_by(
            company_id=context.company_id,
            integration_id=context.integration_id,
            provider_id=provider_id,
            provider_code=context.provider_code,
            request_id=request.request_id,
            operation=request.operation,
            status="approved",
        )
        .with_for_update()
        .first()
    )

    if review is None:
        raise PartnerRequestReviewError(
            "Independent company approval is required for this exact request."
        )
    if review.expires_at <= current:
        raise PartnerRequestReviewError(
            "The partner request approval has expired."
        )
    if (
        review.reviewed_by_user_id is None
        or review.reviewed_by_user_id == review.requested_by_user_id
    ):
        raise PartnerRequestReviewError(
            "The partner request does not have a valid independent approval."
        )

    return review


def mark_partner_service_request_review_prepared(
    session, *, review, actor_user_id=None, now=None
):
    """Consume an approved review after successful preparation and audit flush."""
    if actor_user_id is not None and (
        isinstance(actor_user_id, bool)
        or not isinstance(actor_user_id, int)
        or actor_user_id <= 0
    ):
        raise PartnerRequestReviewError("A valid preparation actor is required.")
    current = _now(now)

    if review.status != "approved":
        raise PartnerRequestReviewError(
            "Only approved reviews can be marked prepared."
        )
    if review.expires_at <= current:
        raise PartnerRequestReviewError(
            "The partner request approval has expired."
        )

    _set_terminal_timestamps(review, current)
    review.status = "prepared"
    review.prepared_at = current

    try:
        _record_event(
            session,
            review=review,
            actor_user_id=actor_user_id,
            event_type="prepared",
            from_status="approved",
            to_status="prepared",
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review preparation persistence failed. Caller must roll back."
        ) from None

    return review


def mark_partner_service_request_review_preparation_rejected(
    session, *, review, reason_code, actor_user_id=None, now=None
):
    """Consume an approved review when the adapter refuses preparation."""
    if actor_user_id is not None and (
        isinstance(actor_user_id, bool)
        or not isinstance(actor_user_id, int)
        or actor_user_id <= 0
    ):
        raise PartnerRequestReviewError("A valid preparation actor is required.")
    current = _now(now)
    if review.status != "approved":
        raise PartnerRequestReviewError(
            "Only approved reviews can be marked preparation rejected."
        )
    if review.expires_at <= current:
        raise PartnerRequestReviewError(
            "The partner request approval has expired."
        )
    if (
        not isinstance(reason_code, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,99}", reason_code) is None
    ):
        raise PartnerRequestReviewError(
            "The adapter preparation error code is invalid."
        )
    if review.prepared_at is not None:
        raise PartnerRequestReviewError(
            "A previously prepared review cannot be preparation rejected."
        )

    _set_terminal_timestamps(review, current)
    review.status = "preparation_rejected"
    try:
        _record_event(
            session,
            review=review,
            actor_user_id=actor_user_id,
            event_type="preparation_rejected",
            from_status="approved",
            to_status="preparation_rejected",
            reason_code=reason_code,
        )
        session.flush()
    except Exception:
        raise PartnerRequestReviewError(
            "Review preparation rejection persistence failed. Caller must roll back."
        ) from None
    return review



def list_company_partner_service_request_reviews(
    session, *, actor, statuses=None, limit=100
):
    """List review records scoped to the authenticated company administrator."""
    if session is None or not callable(getattr(session, "query", None)):
        raise TypeError("A valid database session is required.")

    company_id, _ = _actor_company(actor)

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Review list limit must be between 1 and 100.")

    query = session.query(PartnerServiceRequestReview).filter_by(
        company_id=company_id
    )

    if statuses is not None:
        allowed = {"pending", "approved", "rejected", "expired", "prepared", "preparation_rejected"}
        if not isinstance(statuses, (list, tuple, set, frozenset)):
            raise ValueError("Review statuses must be a collection.")
        if not set(statuses).issubset(allowed):
            raise ValueError("An invalid review status was supplied.")
        query = query.filter(
            PartnerServiceRequestReview.status.in_(tuple(statuses))
        )

    return (
        query.order_by(
            PartnerServiceRequestReview.submitted_at.desc(),
            PartnerServiceRequestReview.id.desc(),
        )
        .limit(limit)
        .all()
    )
