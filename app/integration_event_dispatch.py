"""Bounded, failure-isolated dispatch of integration event batches.

This module accepts event IDs from a trusted caller. Each event is claimed
and processed through the existing worker transaction boundaries.

It does not query for events, schedule work, call providers, or expose
event payloads, credentials, provider responses, or exception messages.
"""

from dataclasses import dataclass

from .integration_event_processing import (
    MAX_PROCESSING_LEASE_SECONDS,
    MIN_PROCESSING_LEASE_SECONDS,
)
from .integration_event_worker import (
    IntegrationEventWorkerError,
    IntegrationEventWorkerOutcome,
    claim_and_process_integration_event,
)
from .integration_event_transaction import IntegrationEventTransactionBoundaryError
from .integration_event_orchestration import PaymentVerificationTransactionError


MAX_INTEGRATION_EVENT_BATCH_SIZE = 50
DEFAULT_INTEGRATION_EVENT_BATCH_SIZE = 25

_ALLOWED_OUTCOMES = frozenset({
    "not_claimed",
    "processed",
    "failed",
    "claim_lost",
    "claim_unavailable",
})


class IntegrationEventDispatchError(ValueError):
    """Raised when a batch request is outside the permitted limits."""


@dataclass(frozen=True)
class IntegrationEventDispatchSummary:
    """Safe aggregate results for one dispatch batch."""

    requested: int
    processed: int
    failed: int
    not_claimed: int
    not_attempted: int
    claim_lost: int
    claim_unavailable: int
    worker_errors: int
    unexpected_errors: int

    def __post_init__(self):
        values = (
            self.requested,
            self.processed,
            self.failed,
            self.not_claimed,
            self.not_attempted,
            self.claim_lost,
            self.claim_unavailable,
            self.worker_errors,
            self.unexpected_errors,
        )

        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Dispatch summary counts must be non-negative integers.")

        outcome_total = (
            self.processed
            + self.failed
            + self.not_claimed
            + self.not_attempted
            + self.claim_lost
            + self.claim_unavailable
            + self.worker_errors
            + self.unexpected_errors
        )

        if outcome_total != self.requested:
            raise ValueError("Dispatch summary counts do not match the requested batch.")


def _validate_batch(event_ids, max_events):
    if not isinstance(event_ids, (list, tuple)):
        raise IntegrationEventDispatchError(
            "Event IDs must be supplied as a list or tuple."
        )

    if (
        isinstance(max_events, bool)
        or not isinstance(max_events, int)
        or not 1 <= max_events <= MAX_INTEGRATION_EVENT_BATCH_SIZE
    ):
        raise IntegrationEventDispatchError(
            "Batch size is outside the permitted range."
        )

    if len(event_ids) > max_events:
        raise IntegrationEventDispatchError(
            "The requested batch exceeds its configured limit."
        )

    seen = set()

    for event_id in event_ids:
        if (
            isinstance(event_id, bool)
            or not isinstance(event_id, int)
            or event_id <= 0
        ):
            raise IntegrationEventDispatchError(
                "Every event ID must be a positive integer."
            )

        if event_id in seen:
            raise IntegrationEventDispatchError(
                "Duplicate event IDs are not permitted in a batch."
            )

        seen.add(event_id)

    return tuple(event_ids)


def dispatch_integration_event_batch(
    event_ids,
    *,
    max_events=DEFAULT_INTEGRATION_EVENT_BATCH_SIZE,
    lease_seconds=300,
    registry=None,
    now=None,
    worker=None,
):
    """Dispatch a bounded batch while isolating individual event failures.

    The caller supplies event IDs. Eligibility is still decided atomically
    by the existing claim service, not by this dispatcher.

    Unexpected per-event exceptions are counted and do not stop later
    events. Transaction-safety errors stop the batch; remaining events
    are counted as not_attempted. Exception details are never returned.
    """

    validated_event_ids = _validate_batch(event_ids, max_events)

    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or not MIN_PROCESSING_LEASE_SECONDS
        <= lease_seconds
        <= MAX_PROCESSING_LEASE_SECONDS
    ):
        raise IntegrationEventDispatchError(
            "Processing lease duration is outside the permitted range."
        )

    process_one = (
        claim_and_process_integration_event
        if worker is None
        else worker
    )

    if not callable(process_one):
        raise IntegrationEventDispatchError(
            "A valid event worker is required."
        )

    counts = {
        "processed": 0,
        "failed": 0,
        "not_claimed": 0,
        "not_attempted": 0,
        "claim_lost": 0,
        "claim_unavailable": 0,
        "worker_errors": 0,
        "unexpected_errors": 0,
    }

    for event_index, event_id in enumerate(validated_event_ids):
        try:
            outcome = process_one(
                event_id,
                lease_seconds=lease_seconds,
                registry=registry,
                now=now,
            )

            if not isinstance(outcome, IntegrationEventWorkerOutcome):
                raise TypeError("The worker returned an invalid result.")

            if outcome.status not in _ALLOWED_OUTCOMES:
                raise ValueError("The worker returned an unsupported result.")

            counts[outcome.status] += 1

        except (
            IntegrationEventWorkerError,
            IntegrationEventTransactionBoundaryError,
            PaymentVerificationTransactionError,
        ):
            # Report worker transaction-safety errors separately.
            counts["worker_errors"] += 1
            counts["not_attempted"] = (
                len(validated_event_ids) - event_index - 1
            )
            break
        except Exception:
            # Do not expose exception messages or sensitive details.
            counts["unexpected_errors"] += 1

    return IntegrationEventDispatchSummary(
        requested=len(validated_event_ids),
        **counts,
    )
