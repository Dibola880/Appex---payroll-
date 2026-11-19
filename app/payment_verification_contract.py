"""Validated payment confirmation contract returned by approved adapters."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


CENT = Decimal("0.01")
MAX_PAYMENT_AMOUNT = Decimal("9999999999.99")


@dataclass(frozen=True)
class PaymentVerificationNotice:
    """Normalised provider confirmation; not proof until adapter-validated."""

    provider_payment_id: str
    amount: Decimal
    currency: str
    outcome: str

    def __post_init__(self):
        if (
            not isinstance(self.provider_payment_id, str)
            or not self.provider_payment_id
            or self.provider_payment_id != self.provider_payment_id.strip()
            or len(self.provider_payment_id) > 200
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.provider_payment_id
            )
        ):
            raise ValueError("Invalid provider payment ID.")

        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise ValueError("Invalid payment currency.")

        if self.outcome != "succeeded":
            raise ValueError("Payment outcome is not successful.")

        try:
            amount = Decimal(str(self.amount))
            quantized = amount.quantize(CENT)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Invalid payment amount.") from None

        if (
            not amount.is_finite()
            or amount <= 0
            or amount > MAX_PAYMENT_AMOUNT
        ):
            raise ValueError("Invalid payment amount.")

        if amount != quantized:
            raise ValueError("Payment amount has unsupported precision.")

        object.__setattr__(self, "amount", amount)
