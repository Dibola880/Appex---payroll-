"""Prepare controlled payroll disbursement batches.

This module records approved payroll instructions only.
It does not contact providers or move money.
The caller owns the database transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from .integration_adapters.payroll import (
    PayrollDisbursementBatchContext,
    PayrollTransferInstruction,
)

from .models import (
    CompanyIntegration,
    Employee,
    IntegrationProvider,
    PayrollDisbursementBatch,
    PayrollDisbursementInstruction,
    PayrollRun,
    Payslip,
)


CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")


class PayrollDisbursementError(ValueError):
    """Raised when a payroll run cannot safely be prepared."""


@dataclass(frozen=True)
class PreparedPayrollDisbursement:
    batch: PayrollDisbursementBatch
    instructions: tuple
    provider_code: str = None
    configuration: object = None


def _positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PayrollDisbursementError(
            "%s must be a positive integer." % label
        )


def _currency(value):
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise PayrollDisbursementError(
            "Currency must be a three-letter uppercase code."
        )
    return value


def _timestamp(value):
    if value is None:
        value = datetime.now(timezone.utc)

    if not isinstance(value, datetime):
        raise TypeError("Preparation time must be a datetime.")

    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def _money(value):
    if isinstance(value, bool) or value is None:
        raise PayrollDisbursementError("Payslip net pay is invalid.")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise PayrollDisbursementError(
            "Payslip net pay is not a valid amount."
        ) from None

    if not amount.is_finite() or amount <= Decimal("0"):
        raise PayrollDisbursementError(
            "Every disbursement instruction must have positive net pay."
        )

    if amount > MAX_AMOUNT:
        raise PayrollDisbursementError(
            "Payslip net pay exceeds the permitted amount."
        )

    if amount != amount.quantize(CENT):
        raise PayrollDisbursementError(
            "Payslip net pay contains fractions of a cent."
        )

    return amount


def _validate_integration(session, integration_id, company_id):
    if integration_id is None:
        return None

    _positive_id(integration_id, "Integration ID")

    result = (
        session.query(CompanyIntegration, IntegrationProvider)
        .join(
            IntegrationProvider,
            IntegrationProvider.id == CompanyIntegration.provider_id,
        )
        .filter(CompanyIntegration.id == integration_id)
        .with_for_update()
        .first()
    )

    if result is None:
        raise PayrollDisbursementError(
            "The selected integration does not exist."
        )

    integration, provider = result

    if not provider.is_enabled:
        raise PayrollDisbursementError(
            "The selected integration provider is disabled."
        )

    capabilities = provider.capabilities
    if (
        not isinstance(capabilities, (list, tuple))
        or "payroll_disbursement" not in capabilities
    ):
        raise PayrollDisbursementError(
            "The selected provider does not declare payroll-disbursement capability."
        )

    if integration.status != "connected":
        raise PayrollDisbursementError(
            "The selected integration is not connected."
        )

    if integration.ownership_scope == "company":
        if integration.company_id != company_id:
            raise PayrollDisbursementError(
                "The selected integration belongs to another company."
            )
    elif integration.ownership_scope == "platform":
        if integration.company_id is not None:
            raise PayrollDisbursementError(
                "The platform integration has an invalid ownership scope."
            )
    else:
        raise PayrollDisbursementError(
            "The selected integration has an invalid ownership scope."
        )

    return integration, provider


def prepare_payroll_disbursement(
    session,
    *,
    company_id,
    payroll_run_id,
    integration_id=None,
    now=None,
):
    """Create one prepared batch for one completed payroll run.

    No commit or rollback is performed. The caller must commit the
    surrounding transaction or roll it back if any later step fails.
    """

    if session is None:
        raise TypeError("A database session is required.")

    _positive_id(company_id, "Company ID")
    _positive_id(payroll_run_id, "Payroll run ID")
    timestamp = _timestamp(now)

    payroll_run = (
        session.query(PayrollRun)
        .filter(
            PayrollRun.id == payroll_run_id,
            PayrollRun.company_id == company_id,
        )
        .with_for_update()
        .first()
    )

    if payroll_run is None:
        raise PayrollDisbursementError(
            "The payroll run was not found for this company."
        )

    # The locked payroll run is the authoritative currency source.
    currency = _currency(payroll_run.currency)

    if payroll_run.status != "Completed":
        raise PayrollDisbursementError(
            "Only completed payroll runs can be prepared for disbursement."
        )

    existing_batch = (
        session.query(PayrollDisbursementBatch)
        .filter(
            PayrollDisbursementBatch.payroll_run_id == payroll_run_id
        )
        .with_for_update()
        .first()
    )

    if existing_batch is not None:
        raise PayrollDisbursementError(
            "A disbursement batch already exists for this payroll run."
        )

    integration_result = _validate_integration(
        session,
        integration_id,
        company_id,
    )
    integration = integration_result[0] if integration_result else None
    provider = integration_result[1] if integration_result else None

    if integration is None:
        prepared_provider_code = None
        prepared_configuration = MappingProxyType({})
    else:
        raw_configuration = integration.configuration or {}
        if not isinstance(raw_configuration, dict):
            raise PayrollDisbursementError(
                "The integration configuration is invalid."
            )
        prepared_provider_code = provider.code
        prepared_configuration = MappingProxyType(dict(raw_configuration))

    rows = (
        session.query(Payslip, Employee)
        .join(Employee, Employee.id == Payslip.employee_id)
        .filter(Payslip.payroll_run_id == payroll_run_id)
        .with_for_update()
        .all()
    )

    if not rows:
        raise PayrollDisbursementError(
            "The completed payroll run has no payslips."
        )

    instructions_data = []
    seen_payslip_ids = set()
    seen_employee_ids = set()
    total_amount = Decimal("0.00")

    for payslip, employee in rows:
        if payslip.payroll_run_id != payroll_run_id:
            raise PayrollDisbursementError(
                "A payslip belongs to another payroll run."
            )

        if employee.company_id != company_id:
            raise PayrollDisbursementError(
                "A payslip employee belongs to another company."
            )

        if payslip.employee_id != employee.id:
            raise PayrollDisbursementError(
                "A payslip employee reference is inconsistent."
            )

        if payslip.id in seen_payslip_ids:
            raise PayrollDisbursementError(
                "The payroll run contains a duplicate payslip."
            )

        if employee.id in seen_employee_ids:
            raise PayrollDisbursementError(
                "The payroll run contains multiple payslips for one employee."
            )

        amount = _money(payslip.net_pay)

        seen_payslip_ids.add(payslip.id)
        seen_employee_ids.add(employee.id)
        total_amount += amount

        if total_amount > MAX_AMOUNT:
            raise PayrollDisbursementError(
                "The payroll disbursement total exceeds the permitted amount."
            )

        instructions_data.append(
            (payslip.id, employee.id, amount)
        )

    batch = PayrollDisbursementBatch(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        integration_id=integration.id if integration is not None else None,
        currency=currency,
        total_amount=total_amount,
        instruction_count=len(instructions_data),
        status="prepared",
        created_at=timestamp,
    )

    session.add(batch)
    session.flush()

    instructions = []

    for payslip_id, employee_id, amount in instructions_data:
        instruction = PayrollDisbursementInstruction(
            batch_id=batch.id,
            payslip_id=payslip_id,
            employee_id=employee_id,
            amount=amount,
            created_at=timestamp,
        )
        session.add(instruction)
        instructions.append(instruction)

    session.flush()

    return PreparedPayrollDisbursement(
        batch=batch,
        instructions=tuple(instructions),
        provider_code=prepared_provider_code,
        configuration=prepared_configuration,
    )


def to_disbursement_adapter_context(prepared):
    """Convert a prepared batch into a validated, immutable adapter context.

    This function performs no database queries and never contacts a provider.
    """
    if type(prepared) is not PreparedPayrollDisbursement:
        raise TypeError("A prepared payroll disbursement is required.")

    batch = prepared.batch
    instructions = prepared.instructions

    if batch.status != "prepared":
        raise PayrollDisbursementError(
            "Only a prepared disbursement batch can be handed to an adapter."
        )

    _positive_id(batch.company_id, "Company ID")
    _positive_id(batch.payroll_run_id, "Payroll run ID")
    _currency(batch.currency)

    if not isinstance(instructions, tuple) or not instructions:
        raise PayrollDisbursementError(
            "The prepared batch must contain instructions."
        )

    if (
        isinstance(batch.instruction_count, bool)
        or not isinstance(batch.instruction_count, int)
        or batch.instruction_count != len(instructions)
    ):
        raise PayrollDisbursementError(
            "The batch instruction count does not match its instructions."
        )

    adapter_instructions = []
    total = Decimal("0.00")

    for item in instructions:
        _positive_id(item.employee_id, "Employee ID")
        _positive_id(item.payslip_id, "Payslip ID")
        amount = _money(item.amount)

        adapter_instructions.append(
            PayrollTransferInstruction(
                employee_id=item.employee_id,
                payslip_id=item.payslip_id,
                amount=amount,
            )
        )
        total += amount

    expected_total = _money(batch.total_amount)
    if total != expected_total:
        raise PayrollDisbursementError(
            "The instruction total does not match the batch total."
        )

    try:
        return PayrollDisbursementBatchContext(
            company_id=batch.company_id,
            payroll_run_id=batch.payroll_run_id,
            currency=batch.currency,
            instructions=tuple(adapter_instructions),
        )
    except (TypeError, ValueError) as exc:
        raise PayrollDisbursementError(
            "The prepared batch failed adapter contract validation."
        ) from exc


def prepare_with_registered_payroll_adapter(
    prepared,
    *,
    registry,
):
    """Prepare through the adapter belonging to the validated integration.

    This does not execute transfers or move money.
    """
    from .integration_adapters.payroll_registry import (
        PayrollDisbursementAdapterRegistry,
    )

    if not isinstance(registry, PayrollDisbursementAdapterRegistry):
        raise TypeError("An explicit payroll adapter registry is required.")

    if type(prepared) is not PreparedPayrollDisbursement:
        raise TypeError("A prepared payroll disbursement is required.")

    _positive_id(prepared.batch.integration_id, "Integration ID")

    if not isinstance(prepared.provider_code, str) or not prepared.provider_code:
        raise PayrollDisbursementError(
            "The prepared batch has no validated provider identity."
        )

    context = to_disbursement_adapter_context(prepared)

    return registry.prepare_disbursement(
        prepared.provider_code,
        batch=context,
        configuration=prepared.configuration,
    )
