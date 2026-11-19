"""Provider-neutral contracts for integration adapters."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Optional

from ..payment_verification_contract import PaymentVerificationNotice


MAX_ADAPTER_WEBHOOK_BODY_BYTES = 1024 * 1024
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_PROVIDER_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ConnectionVerificationResult:
    """A safe, provider-independent verification outcome."""

    success: bool
    error_code: Optional[str] = None

    def __post_init__(self):
        if type(self.success) is not bool:
            raise TypeError("Verification success must be a boolean.")

        if self.success and self.error_code is not None:
            raise ValueError(
                "A successful verification cannot contain an error code."
            )

        if not self.success:
            if (
                not isinstance(self.error_code, str)
                or not _ERROR_CODE_PATTERN.fullmatch(self.error_code)
            ):
                raise ValueError("A failed verification requires a safe error code.")


@dataclass(frozen=True)
class WebhookEventIdentity:
    """Validated event identity extracted by a provider adapter."""

    external_event_id: str
    event_type: str

    def __post_init__(self):
        fields = (
            ("external event ID", self.external_event_id, 200),
            ("event type", self.event_type, 120),
        )

        for label, value, maximum in fields:
            if not isinstance(value, str):
                raise TypeError("%s must be a string." % label)

            if not value or value != value.strip():
                raise ValueError("%s must be non-empty and trimmed." % label)

            if len(value) > maximum:
                raise ValueError("%s exceeds the permitted length." % label)

            if any(ord(character) < 32 or ord(character) == 127
                   for character in value):
                raise ValueError("%s contains control characters." % label)


@dataclass(frozen=True)
class WebhookEventContext:
    """Safe event data supplied to an adapter processing operation.

    This context deliberately excludes raw webhook payloads and ORM objects.
    """

    integration_id: int
    provider_code: str
    external_event_id: str
    event_type: str
    company_id: Optional[int]
    payload_hash: str
    metadata: Mapping = field(default_factory=dict)
    provider_timestamp: Optional[datetime] = None
    verified_at: Optional[datetime] = None

    def __post_init__(self):
        if (
            isinstance(self.integration_id, bool)
            or not isinstance(self.integration_id, int)
            or self.integration_id <= 0
        ):
            raise ValueError("A valid integration ID is required.")

        if (
            self.company_id is not None
            and (
                isinstance(self.company_id, bool)
                or not isinstance(self.company_id, int)
                or self.company_id <= 0
            )
        ):
            raise ValueError("A valid company ID is required.")

        if (
            not isinstance(self.provider_code, str)
            or not _PROVIDER_CODE_PATTERN.fullmatch(self.provider_code)
        ):
            raise ValueError("A valid provider code is required.")

        WebhookEventIdentity(
            external_event_id=self.external_event_id,
            event_type=self.event_type,
        )

        if (
            not isinstance(self.payload_hash, str)
            or not _HASH_PATTERN.fullmatch(self.payload_hash)
        ):
            raise ValueError("A valid payload hash is required.")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("Event metadata must be a mapping.")

        safe_metadata = dict(self.metadata)

        for key, value in safe_metadata.items():
            if not isinstance(key, str):
                raise ValueError("Event metadata keys must be strings.")

            if not isinstance(value, (str, int, bool)):
                raise ValueError("Event metadata values must be scalar.")

            if isinstance(value, str) and any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            ):
                raise ValueError("Event metadata contains control characters.")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(safe_metadata),
        )

        for label, value in (
            ("provider timestamp", self.provider_timestamp),
            ("verification timestamp", self.verified_at),
        ):
            if value is not None and not isinstance(value, datetime):
                raise TypeError("%s must be a datetime." % label)


@dataclass(frozen=True)
class WebhookProcessingResult:
    """A safe outcome returned by a provider event handler."""

    success: bool
    error_code: Optional[str] = None
    payment_notice: Optional[PaymentVerificationNotice] = None

    def __post_init__(self):
        if type(self.success) is not bool:
            raise TypeError("Processing success must be a boolean.")

        if self.payment_notice is not None:
            if type(self.payment_notice) is not PaymentVerificationNotice:
                raise TypeError("Invalid payment verification notice.")

            if not self.success:
                raise ValueError(
                    "Failed processing cannot contain a payment notice."
                )

        if self.success and self.error_code is not None:
            raise ValueError(
                "Successful processing cannot contain an error code."
            )

        if not self.success:
            if (
                not isinstance(self.error_code, str)
                or not _ERROR_CODE_PATTERN.fullmatch(self.error_code)
            ):
                raise ValueError(
                    "Failed processing requires a safe error code."
                )


class IntegrationAdapter(ABC):
    """Interface implemented by explicitly approved provider adapters."""

    @property
    def supported_capabilities(self):
        """Capabilities actually implemented by this adapter."""
        return frozenset()

    @abstractmethod
    def verify_connection(self, *, configuration, credentials):
        """Verify a connection without exposing secrets in the result."""
        raise NotImplementedError

    def parse_webhook_event(self, *, raw_body):
        """Extract identity from an authenticated raw webhook body.

        Implementations must not use unsigned headers, query parameters,
        or separately supplied request fields for event identity.
        """
        raise NotImplementedError(
            "This adapter does not implement webhook event parsing."
        )

    def process_webhook_event(
        self,
        *,
        event,
        configuration,
        credentials,
    ):
        """Process a verified event using its safe event context.

        Raw webhook payloads and ORM objects are not supplied.

        A future approved implementation may retrieve authoritative event
        details from its provider using the event identity. No provider API
        calls are authorised merely by implementing this interface.

        Return WebhookProcessingResult.
        """
        raise NotImplementedError(
            "This adapter does not implement webhook event processing."
        )
