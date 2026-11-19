"""Controlled, provider-neutral contracts for approved partner services."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Optional


_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AMOUNT = re.compile(r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,2})?$")

# Only these operations can be requested through this partner interface.
PARTNER_OPERATION_SCHEMAS = {
    "payroll.compliance_summary": {
        "required": {
            "payroll_run_id": int,
            "pay_period": str,
            "currency": str,
            "employee_count": int,
            "gross_total": str,
            "tax_total": str,
            "uif_total": str,
            "net_total": str,
        },
        "optional": {},
    },
    "financial_services.product_catalogue": {
        "required": {},
        "optional": {
            "product_category": str,
            "currency": str,
        },
    },
    "financial_services.company_offer_request": {
        "required": {
            "company_reference": str,
            "product_code": str,
            "currency": str,
            "requested_amount": str,
            "purpose_code": str,
        },
        "optional": {},
    },
}


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive integer." % label)
    return value


def _safe_text(value, label, maximum=120):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("%s must be non-empty trimmed text." % label)
    if len(value) > maximum:
        raise ValueError("%s exceeds the permitted length." % label)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("%s contains control characters." % label)
    return value


def _validate_currency(value):
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise ValueError("Currency must be three uppercase letters.")


def _validate_amount(value, label, *, positive=False):
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise ValueError("%s must be a plain decimal string with at most two decimals." % label)
    if positive and value in {"0", "0.0", "0.00"}:
        raise ValueError("%s must be greater than zero." % label)


def _validate_payload(operation, payload):
    if operation not in PARTNER_OPERATION_SCHEMAS:
        raise ValueError("Partner operation is not approved.")

    if not isinstance(payload, Mapping):
        raise TypeError("Partner payload must be a mapping.")

    schema = PARTNER_OPERATION_SCHEMAS[operation]
    required = schema["required"]
    optional = schema["optional"]
    allowed = set(required) | set(optional)

    if set(payload) - allowed:
        raise ValueError("Partner payload contains fields not approved for this operation.")

    if set(required) - set(payload):
        raise ValueError("Partner payload is missing required fields.")

    clean = {}

    for key, value in payload.items():
        expected_type = required.get(key, optional.get(key))

        if type(value) is not expected_type:
            raise TypeError("Partner payload field has an invalid type: %s." % key)

        if expected_type is str:
            _safe_text(value, key, 160)

        if key == "currency":
            _validate_currency(value)

        if key in {"gross_total", "tax_total", "uif_total", "net_total"}:
            _validate_amount(value, key)

        if key == "requested_amount":
            _validate_amount(value, key, positive=True)

        if key in {"payroll_run_id", "employee_count"}:
            _positive_id(value, key)

        clean[key] = value

    return MappingProxyType(clean)


@dataclass(frozen=True)
class PartnerServiceContext:
    """Tenant and connection identity; deliberately contains no credentials."""

    company_id: int
    integration_id: int
    provider_code: str
    environment: str
    ownership_scope: str
    integration_company_id: Optional[int] = None

    def __post_init__(self):
        _positive_id(self.company_id, "Company ID")
        _positive_id(self.integration_id, "Integration ID")

        if (
            not isinstance(self.provider_code, str)
            or not _PROVIDER_CODE.fullmatch(self.provider_code)
        ):
            raise ValueError("A valid provider code is required.")

        if self.environment not in {"sandbox", "production"}:
            raise ValueError("Invalid integration environment.")

        if self.ownership_scope == "company":
            _positive_id(self.integration_company_id, "Integration company ID")
            if self.integration_company_id != self.company_id:
                raise ValueError("Company integration does not belong to this tenant.")
        elif self.ownership_scope == "platform":
            if self.integration_company_id is not None:
                raise ValueError("Platform integration must not belong to a company.")
        else:
            raise ValueError("Invalid integration ownership scope.")


@dataclass(frozen=True)
class PartnerServiceRequest:
    """An explicitly scoped request containing only approved data fields."""

    request_id: str
    operation: str
    payload: Mapping

    def __post_init__(self):
        if (
            not isinstance(self.request_id, str)
            or not _REFERENCE.fullmatch(self.request_id)
        ):
            raise ValueError("A valid partner request ID is required.")

        clean_payload = _validate_payload(self.operation, self.payload)
        object.__setattr__(self, "payload", clean_payload)


@dataclass(frozen=True)
class PartnerServicePreparationResult:
    """Preparation result only; it does not mean a partner action occurred."""

    accepted: bool
    partner_reference: Optional[str] = None
    error_code: Optional[str] = None

    def __post_init__(self):
        if type(self.accepted) is not bool:
            raise TypeError("Accepted must be a boolean.")

        if self.partner_reference is not None:
            if (
                not isinstance(self.partner_reference, str)
                or not _REFERENCE.fullmatch(self.partner_reference)
            ):
                raise ValueError("Invalid partner reference.")

        if self.accepted:
            if self.error_code is not None:
                raise ValueError("Accepted preparation cannot contain an error.")
        elif (
            not isinstance(self.error_code, str)
            or not _ERROR_CODE.fullmatch(self.error_code)
        ):
            raise ValueError("Rejected preparation requires a safe error code.")


@dataclass(frozen=True)
class PartnerServiceAuditRecord:
    """Safe audit envelope; never contains submitted payload or credentials."""

    request_id: str
    company_id: int
    integration_id: int
    provider_code: str
    operation: str
    payload_hash: str
    outcome: str
    error_code: Optional[str]
    partner_reference: Optional[str]
    occurred_at: datetime

    def __post_init__(self):
        if (
            not isinstance(self.request_id, str)
            or not _REFERENCE.fullmatch(self.request_id)
        ):
            raise ValueError("Invalid audit request ID.")

        _positive_id(self.company_id, "Company ID")
        _positive_id(self.integration_id, "Integration ID")

        if (
            not isinstance(self.provider_code, str)
            or not _PROVIDER_CODE.fullmatch(self.provider_code)
        ):
            raise ValueError("Invalid audit provider code.")

        if self.operation not in PARTNER_OPERATION_SCHEMAS:
            raise ValueError("Invalid audit operation.")

        if (
            not isinstance(self.payload_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.payload_hash)
        ):
            raise ValueError("Invalid partner payload hash.")

        if self.outcome not in {"prepared", "rejected"}:
            raise ValueError("Invalid partner audit outcome.")

        if self.error_code is not None:
            if (
                not isinstance(self.error_code, str)
                or not _ERROR_CODE.fullmatch(self.error_code)
            ):
                raise ValueError("Invalid audit error code.")

        if self.partner_reference is not None:
            if (
                not isinstance(self.partner_reference, str)
                or not _REFERENCE.fullmatch(self.partner_reference)
            ):
                raise ValueError("Invalid audit partner reference.")

        if self.outcome == "prepared" and self.error_code is not None:
            raise ValueError("Prepared audit records cannot contain an error.")

        if self.outcome == "rejected" and self.error_code is None:
            raise ValueError("Rejected audit records require an error code.")

        if not isinstance(self.occurred_at, datetime):
            raise TypeError("Audit timestamp must be a datetime.")


class PartnerServiceAdapter:
    """Preparation-only partner interface; no network or execution method."""

    @property
    def supported_operations(self):
        return frozenset()

    def prepare_request(self, *, context, request, configuration):
        raise NotImplementedError(
            "This partner adapter does not implement request preparation."
        )
