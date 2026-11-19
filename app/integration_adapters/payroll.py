"""Provider-neutral payroll disbursement contracts.

These contracts support preparation and validation only.
They do not authorize provider calls or movement of money.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

TRANSFER_STATUSES = frozenset({
    "prepared",
    "submitted",
    "processing",
    "settled",
    "failed",
    "reversed",
})


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive integer." % label)


def _positive_amount(value):
    if not isinstance(value, Decimal):
        raise TypeError("Transfer amounts must be Decimal values.")

    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError("Transfer amounts must be finite and positive.")

    if value.as_tuple().exponent < -2:
        raise ValueError("Transfer amounts cannot have fractions of a cent.")

    if value > Decimal("999999999999.99"):
        raise ValueError("Transfer amount exceeds the permitted limit.")

    return value


def _currency(value):
    if not isinstance(value, str) or not _CURRENCY_PATTERN.fullmatch(value):
        raise ValueError("Currency must be a three-letter uppercase code.")
    return value


@dataclass(frozen=True)
class PayrollTransferInstruction:
    """One employee's net-pay instruction, without bank details."""

    employee_id: int
    payslip_id: int
    amount: Decimal

    def __post_init__(self):
        _positive_id(self.employee_id, "Employee ID")
        _positive_id(self.payslip_id, "Payslip ID")
        _positive_amount(self.amount)


@dataclass(frozen=True)
class PayrollDisbursementBatchContext:
    """Immutable, provider-neutral batch supplied to an adapter."""

    company_id: int
    payroll_run_id: int
    currency: str
    instructions: tuple

    def __post_init__(self):
        _positive_id(self.company_id, "Company ID")
        _positive_id(self.payroll_run_id, "Payroll run ID")
        _currency(self.currency)

        if not isinstance(self.instructions, tuple) or not self.instructions:
            raise ValueError("A batch requires at least one instruction.")

        if any(
            type(item) is not PayrollTransferInstruction
            for item in self.instructions
        ):
            raise TypeError("Batch instructions have an invalid type.")

        payslip_ids = [item.payslip_id for item in self.instructions]
        if len(payslip_ids) != len(set(payslip_ids)):
            raise ValueError("A payslip may appear only once in a batch.")

        employee_ids = [item.employee_id for item in self.instructions]
        if len(employee_ids) != len(set(employee_ids)):
            raise ValueError("An employee may appear only once in a batch.")

    @property
    def total_amount(self):
        return sum(
            (item.amount for item in self.instructions),
            Decimal("0.00"),
        )


@dataclass(frozen=True)
class DisbursementPreparationResult:
    """Provider-neutral result of preparing, not executing, a batch."""

    accepted: bool
    provider_reference: str = None
    error_code: str = None

    def __post_init__(self):
        if type(self.accepted) is not bool:
            raise TypeError("Accepted must be a boolean.")

        if self.provider_reference is not None:
            if (
                not isinstance(self.provider_reference, str)
                or not _REFERENCE_PATTERN.fullmatch(self.provider_reference)
            ):
                raise ValueError("Provider reference is invalid.")

        if self.accepted:
            if self.error_code is not None:
                raise ValueError("Accepted preparation cannot contain an error.")
        else:
            if (
                not isinstance(self.error_code, str)
                or not _ERROR_CODE_PATTERN.fullmatch(self.error_code)
            ):
                raise ValueError("Rejected preparation requires a safe error code.")


@dataclass(frozen=True)
class UnverifiedTransferStatusNotice:
    """Untrusted status data; never evidence that funds were transferred."""

    provider_reference: str
    status: str
    received_at: datetime

    def __post_init__(self):
        if (
            not isinstance(self.provider_reference, str)
            or not _REFERENCE_PATTERN.fullmatch(self.provider_reference)
        ):
            raise ValueError("Provider reference is invalid.")

        if self.status not in TRANSFER_STATUSES:
            raise ValueError("Transfer status is unsupported.")

        if not isinstance(self.received_at, datetime):
            raise TypeError("Status notice timestamp must be a datetime.")


class PayrollDisbursementAdapter(ABC):
    """Preparation-only interface. No transfer execution is exposed."""

    @abstractmethod
    def prepare_disbursement(
        self,
        *,
        batch,
        configuration,
    ):
        """Validate or prepare an instruction without moving money.

        Implementations must return DisbursementPreparationResult.
        This interface does not authorize network access.
        """
        raise NotImplementedError
