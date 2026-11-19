"""Transaction boundary for claimed integration event processing.

The event claim must be committed before this service is called.

Successful processing outcomes commit. Unexpected exceptions roll back.
An existing transaction is never committed or rolled back here.
"""

import re

from . import db
from .integration_adapters import DEFAULT_ADAPTER_REGISTRY
from .integration_event_orchestration import (
    IntegrationEventProcessingOutcome,
    process_claimed_integration_event,
)


ALLOWED_PROCESSING_OUTCOMES = frozenset({
    "processed",
    "failed",
    "claim_lost",
    "claim_unavailable",
})


class IntegrationEventTransactionBoundaryError(RuntimeError):
    """Raised when the processing transaction cannot safely complete."""


def process_claimed_integration_event_transactionally(
    event_id,
    *,
    claim_token,
    registry=DEFAULT_ADAPTER_REGISTRY,
    now=None,
    session=None,
):
    """Process one committed claim inside an exclusively owned transaction."""

    transaction_session = db.session if session is None else session

    if not callable(getattr(transaction_session, "in_transaction", None)):
        raise IntegrationEventTransactionBoundaryError(
            "The database session cannot report transaction state."
        )

    if not callable(getattr(transaction_session, "begin", None)):
        raise IntegrationEventTransactionBoundaryError(
            "The database session cannot begin a transaction."
        )

    if transaction_session.in_transaction():
        raise IntegrationEventTransactionBoundaryError(
            "An existing transaction is active; processing was not started."
        )

    # Normal context exit commits. Any exception causes rollback.
    with transaction_session.begin():
        outcome = process_claimed_integration_event(
            event_id,
            claim_token=claim_token,
            registry=registry,
            now=now,
        )

        if not isinstance(outcome, IntegrationEventProcessingOutcome):
            raise IntegrationEventTransactionBoundaryError(
                "Event processing returned an invalid outcome."
            )

        if outcome.status not in ALLOWED_PROCESSING_OUTCOMES:
            raise IntegrationEventTransactionBoundaryError(
                "Event processing returned an unsupported outcome."
            )

        if outcome.status == "failed":
            if (
                not isinstance(outcome.error_code, str)
                or not re.fullmatch(
                    r"[a-z][a-z0-9_]{0,99}",
                    outcome.error_code,
                )
            ):
                raise IntegrationEventTransactionBoundaryError(
                    "Failed processing returned an invalid error code."
                )
        elif outcome.error_code is not None:
            raise IntegrationEventTransactionBoundaryError(
                "A non-failure outcome cannot contain an error code."
            )

    # Reached only after the transaction context exits successfully.
    return outcome
