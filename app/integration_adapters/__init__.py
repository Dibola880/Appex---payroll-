"""Provider-neutral integration adapter interfaces."""

from ..payment_verification_contract import PaymentVerificationNotice

from .base import (
    ConnectionVerificationResult,
    IntegrationAdapter,
    WebhookEventContext,
    WebhookEventIdentity,
    WebhookProcessingResult,
)
from .registry import (
    DEFAULT_ADAPTER_REGISTRY,
    IntegrationAdapterError,
    IntegrationAdapterRegistry,
    IntegrationAdapterUnavailable,
)

__all__ = [
    "PaymentVerificationNotice",
    "ConnectionVerificationResult",
    "IntegrationAdapter",
    "WebhookEventContext",
    "WebhookEventIdentity",
    "WebhookProcessingResult",
    "DEFAULT_ADAPTER_REGISTRY",
    "IntegrationAdapterError",
    "IntegrationAdapterRegistry",
    "IntegrationAdapterUnavailable",
    "DisbursementPreparationResult",
    "PayrollDisbursementAdapter",
    "PayrollDisbursementBatchContext",
    "PayrollTransferInstruction",
    "UnverifiedTransferStatusNotice",
    "DEFAULT_PAYROLL_DISBURSEMENT_REGISTRY",
    "PayrollDisbursementAdapterError",
    "PayrollDisbursementAdapterRegistry",
    "PayrollDisbursementAdapterUnavailable",
]

from .payroll import (
    DisbursementPreparationResult,
    PayrollDisbursementAdapter,
    PayrollDisbursementBatchContext,
    PayrollTransferInstruction,
    UnverifiedTransferStatusNotice,
)


from .payroll_registry import (
    DEFAULT_PAYROLL_DISBURSEMENT_REGISTRY,
    PayrollDisbursementAdapterError,
    PayrollDisbursementAdapterRegistry,
    PayrollDisbursementAdapterUnavailable,
)
