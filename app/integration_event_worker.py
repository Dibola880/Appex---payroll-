"""Claim and process integration events using separate transactions."""

import re
from dataclasses import dataclass
from typing import Optional

from . import db
from .integration_event_processing import claim_integration_event
from .integration_event_transaction import (
    process_claimed_integration_event_transactionally,
)


_WORKER_OUTCOMES = frozenset({
    "not_claimed",
    "processed",
    "failed",
    "claim_lost",
    "claim_unavailable",
})

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class IntegrationEventWorkerError(RuntimeError):
    """Raised when the worker cannot safely manage its transactions."""


@dataclass(frozen=True)
class IntegrationEventWorkerOutcome:
    """Result returned only after the relevant transaction has committed."""

    status: str
    claim_committed: bool
    processing_committed: bool
    error_code: Optional[str] = None

    def __post_init__(self):
        if self.status not in _WORKER_OUTCOMES:
            raise ValueError("Unsupported integration worker outcome.")

        if type(self.claim_committed) is not bool:
            raise ValueError("claim_committed must be a boolean.")

        if type(self.processing_committed) is not bool:
            raise ValueError("processing_committed must be a boolean.")

        if not self.claim_committed:
            raise ValueError("A returned worker outcome requires a committed claim transaction.")

        if self.status == "not_claimed":
            if self.processing_committed or self.error_code is not None:
                raise ValueError("Invalid not_claimed worker outcome.")
            return

        if not self.processing_committed:
            raise ValueError("A claimed event requires a committed processing transaction.")

        if self.status == "failed":
            if (
                not isinstance(self.error_code, str)
                or not _ERROR_CODE_PATTERN.fullmatch(self.error_code)
            ):
                raise ValueError("A failed worker outcome requires a safe error code.")
        elif self.error_code is not None:
            raise ValueError("Only failed outcomes may contain an error code.")


def claim_and_process_integration_event(
    event_id,
    *,
    lease_seconds=300,
    registry=None,
    now=None,
):
    """Commit an event claim, then process it in a separate transaction."""

    session = db.session

    if not callable(getattr(session, "in_transaction", None)):
        raise IntegrationEventWorkerError(
            "The database session cannot report transaction state."
        )

    if not callable(getattr(session, "begin", None)):
        raise IntegrationEventWorkerError(
            "The database session cannot begin a transaction."
        )

    if session.in_transaction():
        raise IntegrationEventWorkerError(
            "An existing transaction is active; worker was not started."
        )

    # Transaction one: claim the event.
    with session.begin():
        claim_token = claim_integration_event(
            event_id,
            lease_seconds=lease_seconds,
            now=now,
        )

    # Reached only after the claim transaction commits.
    if claim_token is None:
        return IntegrationEventWorkerOutcome(
            status="not_claimed",
            claim_committed=True,
            processing_committed=False,
        )

    # Transaction two: processing, payment verification and event completion.
    processing_options = {
        "claim_token": claim_token,
        "now": now,
        "session": session,
    }

    if registry is not None:
        processing_options["registry"] = registry

    outcome = process_claimed_integration_event_transactionally(
        event_id,
        **processing_options,
    )

    # Reached only after the processing transaction commits successfully.
    return IntegrationEventWorkerOutcome(
        status=outcome.status,
        error_code=outcome.error_code,
        claim_committed=True,
        processing_committed=True,
    )
