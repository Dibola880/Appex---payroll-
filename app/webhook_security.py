"""Webhook signature verification and replay protection.

This module implements an explicit HMAC-SHA256 webhook profile.
It does not assume that every provider uses this signature format.
"""

import hashlib
import hmac
import re

from datetime import datetime, timezone

from .integration_security import (
    IntegrationCredentialError,
    decrypt_credentials,
)


DEFAULT_TOLERANCE_SECONDS = 300
SIGNATURE_PATTERN = re.compile(r"^sha256=([0-9a-f]{64})$")


class WebhookSecurityError(Exception):
    """Raised when a webhook cannot be safely authenticated."""


def _utc_now(value=None):
    if value is None:
        return datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise WebhookSecurityError("Invalid verification time.")

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _parse_provider_timestamp(timestamp):
    if isinstance(timestamp, bool):
        raise WebhookSecurityError("Invalid webhook timestamp.")

    if isinstance(timestamp, int):
        value = timestamp
    elif (
        isinstance(timestamp, str)
        and 1 <= len(timestamp) <= 12
        and timestamp.isascii()
        and timestamp.isdigit()
    ):
        value = int(timestamp)
    else:
        raise WebhookSecurityError("Invalid webhook timestamp.")

    if value <= 0:
        raise WebhookSecurityError("Invalid webhook timestamp.")

    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise WebhookSecurityError(
            "Invalid webhook timestamp."
        ) from None


def verify_hmac_sha256_signature(
    *,
    secret,
    raw_body,
    signature,
    timestamp,
    now=None,
    tolerance_seconds=DEFAULT_TOLERANCE_SECONDS,
):
    """Verify timestamp-bound HMAC-SHA256 webhook signatures.

    Signed message format:
        ASCII(timestamp) + b"." + raw_body

    Signature header format:
        sha256=<64 lowercase hexadecimal characters>

    Returns the provider timestamp as a timezone-naive UTC datetime,
    suitable for the existing SQLAlchemy DateTime columns.
    """

    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 16:
        raise WebhookSecurityError("Webhook signing secret is invalid.")

    if not isinstance(raw_body, bytes):
        raise WebhookSecurityError("Webhook body must be raw bytes.")

    if not isinstance(signature, str):
        raise WebhookSecurityError("Webhook signature is invalid.")

    match = SIGNATURE_PATTERN.fullmatch(signature)
    if match is None:
        raise WebhookSecurityError("Webhook signature is invalid.")

    if (
        isinstance(tolerance_seconds, bool)
        or not isinstance(tolerance_seconds, int)
        or not 1 <= tolerance_seconds <= 900
    ):
        raise WebhookSecurityError("Webhook tolerance is invalid.")

    provider_time = _parse_provider_timestamp(timestamp)
    current_time = _utc_now(now)

    age_seconds = abs((current_time - provider_time).total_seconds())

    if age_seconds > tolerance_seconds:
        raise WebhookSecurityError("Webhook timestamp is outside the allowed window.")

    signed_message = str(timestamp).encode("ascii") + b"." + raw_body

    expected = hmac.new(
        secret.encode("utf-8"),
        signed_message,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, match.group(1)):
        raise WebhookSecurityError("Webhook signature verification failed.")

    return provider_time.replace(tzinfo=None)


def verify_integration_webhook(
    *,
    integration,
    raw_body,
    signature,
    timestamp,
    now=None,
    tolerance_seconds=DEFAULT_TOLERANCE_SECONDS,
):
    """Verify a webhook using an integration's encrypted signing secret.

    The encrypted credentials must contain a string field named
    ``webhook_signing_secret``.

    No decrypted credential is returned or logged.
    """

    if integration is None:
        raise WebhookSecurityError("Integration connection is required.")

    if getattr(integration, "status", None) == "disabled":
        raise WebhookSecurityError("Integration connection is disabled.")

    encrypted = getattr(integration, "credentials_encrypted", None)
    key_version = getattr(integration, "credential_key_version", None)

    if not encrypted or not key_version:
        raise WebhookSecurityError("Webhook credentials are unavailable.")

    try:
        credentials = decrypt_credentials(encrypted, key_version)
    except IntegrationCredentialError:
        raise WebhookSecurityError(
            "Webhook credentials could not be verified."
        ) from None

    if not isinstance(credentials, dict):
        raise WebhookSecurityError("Webhook credentials are invalid.")

    secret = credentials.get("webhook_signing_secret")

    if not isinstance(secret, str):
        raise WebhookSecurityError("Webhook signing secret is unavailable.")

    return verify_hmac_sha256_signature(
        secret=secret,
        raw_body=raw_body,
        signature=signature,
        timestamp=timestamp,
        now=now,
        tolerance_seconds=tolerance_seconds,
    )
