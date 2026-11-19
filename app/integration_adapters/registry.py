"""Explicit allowlist registry for provider integration adapters."""

import re

from .base import (
    IntegrationAdapter,
    MAX_ADAPTER_WEBHOOK_BODY_BYTES,
    WebhookEventIdentity,
    WebhookEventContext,
    WebhookProcessingResult,
)


class IntegrationAdapterError(ValueError):
    """Base error for adapter registry operations."""


class IntegrationAdapterUnavailable(IntegrationAdapterError):
    """Raised when an approved adapter or capability is unavailable."""


_PROVIDER_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{1,79}")
_CAPABILITY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,79}")


def _normalise_provider_code(provider_code):
    if not isinstance(provider_code, str):
        raise IntegrationAdapterError("Provider code is required.")

    code = provider_code.strip().lower()

    if not _PROVIDER_CODE_PATTERN.fullmatch(code):
        raise IntegrationAdapterError("Invalid provider code.")

    return code


def _validate_capability_collection(capabilities, label):
    if not isinstance(capabilities, (list, tuple, set, frozenset)):
        raise IntegrationAdapterError(
            "%s must be a collection of capability codes." % label
        )

    validated = set()

    for capability in capabilities:
        if (
            not isinstance(capability, str)
            or not _CAPABILITY_PATTERN.fullmatch(capability)
        ):
            raise IntegrationAdapterError(
                "%s contains an invalid capability code." % label
            )

        if capability in validated:
            raise IntegrationAdapterError(
                "%s contains duplicate capability codes." % label
            )

        validated.add(capability)

    return frozenset(validated)


class IntegrationAdapterRegistry:
    """Stores explicitly registered adapter instances.

    No dynamic imports, module paths, or user-controlled adapter loading.
    """

    def __init__(self):
        self._adapters = {}
        self._capabilities = {}

    def register(self, provider_code, adapter):
        code = _normalise_provider_code(provider_code)

        if not isinstance(adapter, IntegrationAdapter):
            raise IntegrationAdapterError(
                "Adapter must implement IntegrationAdapter."
            )

        if code in self._adapters:
            raise IntegrationAdapterError(
                "An adapter is already registered for this provider."
            )

        try:
            capabilities = _validate_capability_collection(
                adapter.supported_capabilities,
                "Adapter capabilities",
            )
        except IntegrationAdapterError:
            raise
        except Exception:
            raise IntegrationAdapterError(
                "Adapter capabilities could not be validated."
            ) from None

        self._adapters[code] = adapter
        self._capabilities[code] = capabilities

        return adapter

    def get(self, provider_code):
        code = _normalise_provider_code(provider_code)
        adapter = self._adapters.get(code)

        if adapter is None:
            raise IntegrationAdapterUnavailable(
                "No approved adapter is registered for this provider."
            )

        return adapter

    def has(self, provider_code):
        code = _normalise_provider_code(provider_code)
        return code in self._adapters

    def validate_capabilities(self, provider_code, provider_capabilities):
        """Reject catalogue capabilities not implemented by the adapter."""
        code = _normalise_provider_code(provider_code)

        if code not in self._adapters:
            raise IntegrationAdapterUnavailable(
                "No approved adapter is registered for this provider."
            )

        declared = _validate_capability_collection(
            provider_capabilities,
            "Provider capabilities",
        )

        supported = self._capabilities[code]
        unsupported = declared - supported

        if unsupported:
            raise IntegrationAdapterError(
                "Provider declares capabilities unsupported by its adapter."
            )

        return True

    def parse_webhook_event(self, provider_code, *, raw_body):
        """Parse event identity after the caller authenticates raw_body.

        This method deliberately does not verify signatures itself. Callers
        must authenticate the exact body before invoking the provider parser.
        """
        if not isinstance(raw_body, bytes):
            raise IntegrationAdapterError(
                "Webhook body must be raw bytes."
            )

        if not raw_body or len(raw_body) > MAX_ADAPTER_WEBHOOK_BODY_BYTES:
            raise IntegrationAdapterError(
                "Webhook body is empty or exceeds the permitted size."
            )

        adapter = self.get(provider_code)

        try:
            result = adapter.parse_webhook_event(raw_body=raw_body)
        except NotImplementedError:
            raise IntegrationAdapterUnavailable(
                "This provider adapter does not support webhook parsing."
            ) from None
        except IntegrationAdapterError:
            raise
        except Exception:
            raise IntegrationAdapterError(
                "Provider webhook parsing failed."
            ) from None

        if type(result) is not WebhookEventIdentity:
            raise IntegrationAdapterError(
                "Provider adapter returned an invalid webhook identity."
            )

        return result


    def process_webhook_event(
        self,
        provider_code,
        *,
        event,
        configuration,
        credentials,
    ):
        """Invoke an explicitly registered adapter with safe event context."""
        if type(event) is not WebhookEventContext:
            raise IntegrationAdapterError(
                "A validated webhook event context is required."
            )

        if not isinstance(configuration, dict):
            raise IntegrationAdapterError(
                "Provider configuration must be a dictionary."
            )

        if not isinstance(credentials, dict):
            raise IntegrationAdapterError(
                "Provider credentials must be a dictionary."
            )

        adapter = self.get(provider_code)

        if event.provider_code != provider_code.strip().lower():
            raise IntegrationAdapterError(
                "Event provider does not match the registered adapter."
            )

        try:
            result = adapter.process_webhook_event(
                event=event,
                configuration=configuration,
                credentials=credentials,
            )
        except NotImplementedError:
            raise IntegrationAdapterUnavailable(
                "This provider adapter does not support event processing."
            ) from None
        except IntegrationAdapterError:
            raise
        except Exception:
            raise IntegrationAdapterError(
                "Provider event processing failed."
            ) from None

        if type(result) is not WebhookProcessingResult:
            raise IntegrationAdapterError(
                "Provider adapter returned an invalid processing result."
            )

        return result


# Deliberately empty. Provider adapters require explicit approval and
# registration in application code.
DEFAULT_ADAPTER_REGISTRY = IntegrationAdapterRegistry()
