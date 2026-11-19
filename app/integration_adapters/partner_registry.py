"""Explicit allowlist registry for controlled partner-service adapters."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType

from .partner import (
    PARTNER_OPERATION_SCHEMAS,
    PartnerServiceAdapter,
    PartnerServiceAuditRecord,
    PartnerServiceContext,
    PartnerServicePreparationResult,
    PartnerServiceRequest,
)


_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_CONFIG_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_FORBIDDEN_CONFIG_TERMS = (
    "secret", "password", "credential", "apikey",
    "accesstoken", "refreshtoken", "privatekey",
    "authorization", "accountnumber", "iban",
    "swift", "routing", "bankaccount",
)


class PartnerServiceRegistryError(ValueError):
    """Base error for partner registry validation."""


class PartnerServiceUnavailable(PartnerServiceRegistryError):
    """Raised when a partner or requested operation is unavailable."""


def _provider_code(value):
    if not isinstance(value, str) or not _PROVIDER_CODE.fullmatch(value):
        raise PartnerServiceRegistryError("Invalid partner provider code.")
    return value


def _capabilities(values, label):
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise PartnerServiceRegistryError(
            "%s must be a collection of operation codes." % label
        )

    result = set()
    for value in values:
        if (
            not isinstance(value, str)
            or value not in PARTNER_OPERATION_SCHEMAS
        ):
            raise PartnerServiceRegistryError(
                "%s contains an unsupported operation." % label
            )
        if value in result:
            raise PartnerServiceRegistryError(
                "%s contains duplicate operations." % label
            )
        result.add(value)

    return frozenset(result)


def _safe_configuration(configuration):
    if not isinstance(configuration, Mapping):
        raise PartnerServiceRegistryError(
            "Partner configuration must be a mapping."
        )

    clean = {}
    for key, value in configuration.items():
        if not isinstance(key, str) or not _CONFIG_KEY.fullmatch(key):
            raise PartnerServiceRegistryError(
                "Partner configuration contains an invalid key."
            )

        normalised = re.sub(r"[^a-z0-9]", "", key.lower())
        if any(term in normalised for term in _FORBIDDEN_CONFIG_TERMS):
            raise PartnerServiceRegistryError(
                "Secret or banking configuration is not permitted here."
            )

        if value is None or type(value) in {str, bool, int}:
            if isinstance(value, str) and len(value) > 500:
                raise PartnerServiceRegistryError(
                    "Partner configuration value is too long."
                )
        elif type(value) is float:
            if not math.isfinite(value):
                raise PartnerServiceRegistryError(
                    "Partner configuration contains a non-finite number."
                )
        else:
            raise PartnerServiceRegistryError(
                "Partner configuration values must be simple scalars."
            )

        clean[key] = value

    return MappingProxyType(clean)


class PartnerServiceAdapterRegistry:
    """Stores explicitly registered adapters; never loads providers dynamically."""

    def __init__(self):
        self._adapters = {}

    def register(self, provider_code, adapter):
        code = _provider_code(provider_code)

        if not isinstance(adapter, PartnerServiceAdapter):
            raise PartnerServiceRegistryError(
                "Adapter must implement PartnerServiceAdapter."
            )

        if code in self._adapters:
            raise PartnerServiceRegistryError(
                "A partner adapter is already registered for this provider."
            )

        try:
            supported = _capabilities(
                adapter.supported_operations,
                "Adapter operations",
            )
        except PartnerServiceRegistryError:
            raise
        except Exception:
            raise PartnerServiceRegistryError(
                "Partner adapter operations could not be validated."
            ) from None

        if not supported:
            raise PartnerServiceRegistryError(
                "A partner adapter must declare at least one operation."
            )

        self._adapters[code] = (adapter, supported)
        return adapter

    def get(self, provider_code):
        code = _provider_code(provider_code)
        registered = self._adapters.get(code)

        if registered is None:
            raise PartnerServiceUnavailable(
                "No approved partner adapter is registered."
            )

        return registered[0]

    def prepare_request(
        self,
        provider_code,
        *,
        context,
        request,
        provider_capabilities,
        configuration,
    ):
        code = _provider_code(provider_code)

        if type(context) is not PartnerServiceContext:
            raise PartnerServiceRegistryError(
                "A validated partner service context is required."
            )

        if type(request) is not PartnerServiceRequest:
            raise PartnerServiceRegistryError(
                "A validated partner service request is required."
            )

        if context.provider_code != code:
            raise PartnerServiceRegistryError(
                "Partner context does not match the registered provider."
            )

        declared = _capabilities(
            provider_capabilities,
            "Provider capabilities",
        )

        self.get(code)
        _, supported = self._adapters[code]

        if request.operation not in declared:
            raise PartnerServiceUnavailable(
                "Provider catalogue does not declare this operation."
            )

        if request.operation not in supported:
            raise PartnerServiceUnavailable(
                "Registered adapter does not support this operation."
            )

        safe_configuration = _safe_configuration(configuration)

        try:
            result = self._adapters[code][0].prepare_request(
                context=context,
                request=request,
                configuration=safe_configuration,
            )
        except NotImplementedError:
            raise PartnerServiceUnavailable(
                "Partner adapter does not implement request preparation."
            ) from None
        except Exception:
            raise PartnerServiceRegistryError(
                "Partner request preparation failed."
            ) from None

        if type(result) is not PartnerServicePreparationResult:
            raise PartnerServiceRegistryError(
                "Partner adapter returned an invalid preparation result."
            )

        return result


def build_partner_service_audit_record(
    *,
    context,
    request,
    result,
    now=None,
):
    """Build a safe audit envelope without retaining submitted payload data."""

    if type(context) is not PartnerServiceContext:
        raise TypeError("A validated partner context is required.")
    if type(request) is not PartnerServiceRequest:
        raise TypeError("A validated partner request is required.")
    if type(result) is not PartnerServicePreparationResult:
        raise TypeError("A validated preparation result is required.")

    canonical_payload = json.dumps(
        dict(request.payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    payload_hash = hashlib.sha256(canonical_payload).hexdigest()

    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)

    return PartnerServiceAuditRecord(
        request_id=request.request_id,
        company_id=context.company_id,
        integration_id=context.integration_id,
        provider_code=context.provider_code,
        operation=request.operation,
        payload_hash=payload_hash,
        outcome="prepared" if result.accepted else "rejected",
        error_code=result.error_code,
        partner_reference=result.partner_reference,
        occurred_at=timestamp,
    )


# Deliberately empty. Registration requires an explicit application decision.
DEFAULT_PARTNER_SERVICE_REGISTRY = PartnerServiceAdapterRegistry()
