"""Safe, lease-based processing of verified integration events.

All operations use conditional database updates and leave transaction
ownership with the caller. This module never commits or rolls back.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, update

from . import db
from .models import IntegrationEvent


DEFAULT_PROCESSING_LEASE_SECONDS = 300
MIN_PROCESSING_LEASE_SECONDS = 30
MAX_PROCESSING_LEASE_SECONDS = 3600
MAX_PROCESSING_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600)

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class IntegrationEventProcessingError(ValueError):
    """Raised when an event processing operation is invalid."""


def _utc_naive(value=None):
    if value is None:
        value = datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise IntegrationEventProcessingError(
            "A valid processing timestamp is required."
        )

    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_event_id(event_id):
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
    ):
        raise IntegrationEventProcessingError(
            "A valid integration event ID is required."
        )


def _validate_lease_seconds(lease_seconds):
    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or not MIN_PROCESSING_LEASE_SECONDS
        <= lease_seconds
        <= MAX_PROCESSING_LEASE_SECONDS
    ):
        raise IntegrationEventProcessingError(
            "Processing lease duration is outside the permitted range."
        )


def _validate_token(token):
    if (
        not isinstance(token, str)
        or not token
        or len(token) != 64
        or not re.fullmatch(r"[0-9a-f]{64}", token)
    ):
        raise IntegrationEventProcessingError(
            "A valid processing claim token is required."
        )


def _validate_error_code(error_code):
    if (
        not isinstance(error_code, str)
        or not _ERROR_CODE_PATTERN.fullmatch(error_code)
    ):
        raise IntegrationEventProcessingError(
            "A safe processing error code is required."
        )


def claim_integration_event(
    event_id,
    *,
    lease_seconds=DEFAULT_PROCESSING_LEASE_SECONDS,
    now=None,
):
    """Atomically claim a verified, failed, or abandoned event.

    Returns a new claim token, or None if another worker owns the event
    or the event is not eligible. The caller must commit the transaction
    before beginning external processing.
    """
    _validate_event_id(event_id)
    _validate_lease_seconds(lease_seconds)

    claimed_at = _utc_naive(now)
    lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
    token = secrets.token_hex(32)

    # Expired fifth attempts are terminal, not eligible for another claim.
    db.session.execute(
        update(IntegrationEvent)
        .where(
            IntegrationEvent.id == event_id,
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_lease_expires_at.is_not(None),
            IntegrationEvent.processing_lease_expires_at <= claimed_at,
            IntegrationEvent.processing_attempts >= MAX_PROCESSING_ATTEMPTS,
        )
        .values(
            status="dead_letter",
            processing_token=None,
            processing_started_at=None,
            processing_lease_expires_at=None,
            next_attempt_at=None,
            error_code="max_attempts_exceeded",
        )
        .execution_options(synchronize_session=False)
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
                IntegrationEvent.next_attempt_at <= claimed_at,
            ),
        ),
        and_(
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_lease_expires_at.is_not(None),
            IntegrationEvent.processing_lease_expires_at <= claimed_at,
            IntegrationEvent.processing_attempts < MAX_PROCESSING_ATTEMPTS,
        ),
    )

    statement = (
        update(IntegrationEvent)
        .where(
            IntegrationEvent.id == event_id,
            eligible,
        )
        .values(
            status="processing",
            processing_token=token,
            processing_started_at=claimed_at,
            processing_lease_expires_at=lease_expires_at,
            processing_attempts=(
                func.coalesce(IntegrationEvent.processing_attempts, 0) + 1
            ),
            next_attempt_at=None,
            error_code=None,
        )
        .execution_options(synchronize_session=False)
    )

    result = db.session.execute(statement)

    if result.rowcount != 1:
        return None

    return token


def complete_integration_event(
    event_id,
    *,
    claim_token,
    now=None,
):
    """Complete an event only when the caller still owns its claim."""
    _validate_event_id(event_id)
    _validate_token(claim_token)

    completed_at = _utc_naive(now)

    statement = (
        update(IntegrationEvent)
        .where(
            IntegrationEvent.id == event_id,
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_token == claim_token,
            IntegrationEvent.processing_lease_expires_at > completed_at,
        )
        .values(
            status="processed",
            processed_at=completed_at,
            processing_token=None,
            processing_started_at=None,
            processing_lease_expires_at=None,
            next_attempt_at=None,
            error_code=None,
        )
        .execution_options(synchronize_session=False)
    )

    result = db.session.execute(statement)
    return result.rowcount == 1


def fail_integration_event(
    event_id,
    *,
    claim_token,
    error_code,
    now=None,
):
    """Fail an event only when the caller still owns its claim."""
    _validate_event_id(event_id)
    _validate_token(claim_token)
    _validate_error_code(error_code)

    failed_at = _utc_naive(now)

    statement = (
        update(IntegrationEvent)
        .where(
            IntegrationEvent.id == event_id,
            IntegrationEvent.status == "processing",
            IntegrationEvent.processing_token == claim_token,
            IntegrationEvent.processing_lease_expires_at > failed_at,
        )
        .values(
            status=case(
                (
                    IntegrationEvent.processing_attempts >= MAX_PROCESSING_ATTEMPTS,
                    "dead_letter",
                ),
                else_="failed",
            ),
            processing_token=None,
            processing_started_at=None,
            processing_lease_expires_at=None,
            next_attempt_at=case(
                (
                    IntegrationEvent.processing_attempts == 1,
                    failed_at + timedelta(seconds=RETRY_DELAYS_SECONDS[0]),
                ),
                (
                    IntegrationEvent.processing_attempts == 2,
                    failed_at + timedelta(seconds=RETRY_DELAYS_SECONDS[1]),
                ),
                (
                    IntegrationEvent.processing_attempts == 3,
                    failed_at + timedelta(seconds=RETRY_DELAYS_SECONDS[2]),
                ),
                (
                    IntegrationEvent.processing_attempts == 4,
                    failed_at + timedelta(seconds=RETRY_DELAYS_SECONDS[3]),
                ),
                else_=None,
            ),
            error_code=case(
                (
                    IntegrationEvent.processing_attempts >= MAX_PROCESSING_ATTEMPTS,
                    "max_attempts_exceeded",
                ),
                else_=error_code,
            ),
        )
        .execution_options(synchronize_session=False)
    )

    result = db.session.execute(statement)
    return result.rowcount == 1
