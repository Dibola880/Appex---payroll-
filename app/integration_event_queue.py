"""Read-only, bounded discovery of integration events for dispatch."""

from datetime import datetime, timezone

from sqlalchemy import and_, or_

from . import db
from .models import IntegrationEvent
from .integration_event_processing import MAX_PROCESSING_ATTEMPTS


DEFAULT_QUEUE_BATCH_SIZE = 25
MAX_QUEUE_BATCH_SIZE = 50


class IntegrationEventQueueError(ValueError):
    """Raised when an event queue selection request is invalid."""


def _normalise_now(value=None):
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    if not isinstance(value, datetime):
        raise IntegrationEventQueueError(
            "A valid queue selection timestamp is required."
        )

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def list_dispatchable_integration_event_ids(
    *,
    limit=DEFAULT_QUEUE_BATCH_SIZE,
    now=None,
    session=None,
):
    """Return oldest eligible event IDs without claiming or modifying them.

    Final eligibility is decided by claim_integration_event(), which
    performs the atomic conditional update in its own transaction.
    """

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_QUEUE_BATCH_SIZE
    ):
        raise IntegrationEventQueueError(
            "Queue batch size is outside the permitted range."
        )

    selected_at = _normalise_now(now)
    query_session = db.session if session is None else session

    if not callable(getattr(query_session, "query", None)):
        raise IntegrationEventQueueError(
            "A valid query session is required."
        )

    eligible = or_(
        and_(
            IntegrationEvent.status == "verified",
            IntegrationEvent.processing_attempts < MAX_PROCESSING_ATTEMPTS,
        ),
        and_(
            IntegrationEvent.status == "failed",
            IntegrationEvent.processing_attempts < MAX_PROCESSING_ATTEMPTS,
            or_(
                IntegrationEvent.next_attempt_at.is_(None),
                IntegrationEvent.next_attempt_at <= selected_at,
            ),
        ),
        and_(
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_lease_expires_at.is_not(None),
            IntegrationEvent.processing_lease_expires_at <= selected_at,
        ),
    )

    rows = (
        query_session.query(IntegrationEvent.id)
        .filter(eligible)
        .order_by(
            IntegrationEvent.received_at.asc(),
            IntegrationEvent.id.asc(),
        )
        .limit(limit)
        .all()
    )

    return tuple(row[0] for row in rows)


def dispatch_next_integration_event_batch(
    *,
    limit=DEFAULT_QUEUE_BATCH_SIZE,
    lease_seconds=300,
    registry=None,
    now=None,
    session_factory=None,
    dispatcher=None,
):
    """Discover a bounded batch, close discovery, then dispatch its IDs.

    Discovery uses a short-lived session so its read transaction cannot
    interfere with the worker's independent claim and processing
    transactions.
    """

    factory = db.session if session_factory is None else session_factory

    if not callable(factory):
        raise IntegrationEventQueueError(
            "A valid selection session factory is required."
        )

    selection_session = factory()
    close = getattr(selection_session, "close", None)

    if not callable(close):
        raise IntegrationEventQueueError(
            "The selection session must support close()."
        )

    try:
        event_ids = list_dispatchable_integration_event_ids(
            limit=limit,
            now=now,
            session=selection_session,
        )
    finally:
        close()

    if dispatcher is None:
        from .integration_event_dispatch import (
            dispatch_integration_event_batch,
        )

        dispatch_function = dispatch_integration_event_batch
    else:
        dispatch_function = dispatcher

    if not callable(dispatch_function):
        raise IntegrationEventQueueError(
            "A valid batch dispatcher is required."
        )

    return dispatch_function(
        event_ids,
        max_events=limit,
        lease_seconds=lease_seconds,
        registry=registry,
        now=now,
    )
