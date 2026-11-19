"""Explicit allowlist for payroll disbursement adapters.

The default registry is empty. Registering an adapter requires an explicit
application-level decision. No dynamic imports or automatic provider discovery.
"""
import math
import re
from collections.abc import Mapping
from types import MappingProxyType

from .payroll import (
    DisbursementPreparationResult,
    PayrollDisbursementAdapter,
    PayrollDisbursementBatchContext,
)


_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")

_FORBIDDEN_CONFIGURATION_TERMS = (
    "secret",
    "password",
    "credential",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "privatekey",
    "authorization",
    "accountnumber",
    "iban",
    "swift",
    "routing",
    "bankaccount",
)


class PayrollDisbursementAdapterError(RuntimeError):
    """Safe error raised by the payroll adapter registry."""


class PayrollDisbursementAdapterUnavailable(
    PayrollDisbursementAdapterError
):
    """No explicitly registered adapter exists for this provider."""


def _validated_configuration(configuration):
    if not isinstance(configuration, Mapping):
        raise TypeError("Adapter configuration must be a dictionary.")

    safe = {}

    for key, value in configuration.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 80
        ):
            raise ValueError("Adapter configuration contains an invalid key.")

        normalized = re.sub(r"[^a-z0-9]", "", key.lower())

        if any(term in normalized for term in _FORBIDDEN_CONFIGURATION_TERMS):
            raise ValueError(
                "Sensitive credentials or banking details are not accepted."
            )

        if value is not None and type(value) not in (str, bool, int, float):
            raise ValueError(
                "Adapter configuration values must be simple scalar values."
            )

        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Adapter configuration contains an invalid number.")

        if isinstance(value, str) and len(value) > 500:
            raise ValueError("Adapter configuration value is too long.")

        safe[key] = value

    return MappingProxyType(safe)


class PayrollDisbursementAdapterRegistry:
    """Explicit provider-code to adapter-instance allowlist."""

    def __init__(self):
        self._adapters = {}

    def register(self, provider_code, adapter):
        if (
            not isinstance(provider_code, str)
            or not _PROVIDER_CODE.fullmatch(provider_code)
        ):
            raise ValueError("Provider code is invalid.")

        if not isinstance(adapter, PayrollDisbursementAdapter):
            raise TypeError(
                "Adapter must implement PayrollDisbursementAdapter."
            )

        if provider_code in self._adapters:
            raise ValueError("A payroll adapter is already registered.")

        self._adapters[provider_code] = adapter

    def get(self, provider_code):
        adapter = self._adapters.get(provider_code)

        if adapter is None:
            raise PayrollDisbursementAdapterUnavailable(
                "No approved payroll adapter is registered."
            )

        return adapter

    def prepare_disbursement(
        self,
        provider_code,
        *,
        batch,
        configuration,
    ):
        if type(batch) is not PayrollDisbursementBatchContext:
            raise TypeError("A validated payroll batch context is required.")

        adapter = self.get(provider_code)
        safe_configuration = _validated_configuration(configuration)

        try:
            result = adapter.prepare_disbursement(
                batch=batch,
                configuration=safe_configuration,
            )
        except Exception:
            raise PayrollDisbursementAdapterError(
                "The payroll adapter preparation failed."
            ) from None

        if type(result) is not DisbursementPreparationResult:
            raise PayrollDisbursementAdapterError(
                "The payroll adapter returned an invalid result."
            )

        return result


# Intentionally empty. No live provider adapter is registered.
DEFAULT_PAYROLL_DISBURSEMENT_REGISTRY = (
    PayrollDisbursementAdapterRegistry()
)
