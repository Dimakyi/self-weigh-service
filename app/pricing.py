
"""Pure pricing logic: easy to test, no I/O. Each airline supplies its own policy."""
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING


@dataclass(frozen=True)
class Policy:
    allowance_kg: float
    max_bag_kg: float
    excess_rate_cents_per_kg: int


@dataclass(frozen=True)
class Quote:
    weight_kg: float
    within_allowance: bool
    excess_kg: int
    fee_cents: int
    rejected: bool = False
    reason: str = ""


def quote(weight_kg: float, policy: Policy) -> Quote:
    """Weight + airline policy in, quote out. Excess is charged per started kg. Money in cents."""

    # Reject invalid scale readings, including NaN and infinity.
    if not math.isfinite(weight_kg) or weight_kg <= 0:
        return Quote(
            weight_kg, False, 0, 0, True, "Invalid weight reading"
        )

    if weight_kg > policy.max_bag_kg:
        return Quote(
            weight_kg, False, 0, 0, True,
            f"Bag exceeds {policy.max_bag_kg:.0f} kg limit; take it to the heavy-bag counter"
        )

    if weight_kg <= policy.allowance_kg:
        return Quote(weight_kg, True, 0, 0)

    # Decimal avoids floating-point boundary errors when rounding up.
    excess_decimal = (
        Decimal(str(weight_kg)) - Decimal(str(policy.allowance_kg))
    )
    excess = int(
        excess_decimal.to_integral_value(rounding=ROUND_CEILING)
    )

    return Quote(
        weight_kg,
        False,
        excess,
        excess * policy.excess_rate_cents_per_kg
    )
