"""Deterministic out-of-pocket cost estimate.

Design rule: the LLM *reads* the policy (which cost rule applies to this
service - copay? coinsurance? does the deductible apply?) and Python does the
*math*. Language models are unreliable at multi-step arithmetic; this function
is not, and it's unit-tested.

The order of operations mirrors how US plans actually apply cost-sharing:
    1. if the deductible applies, you pay until the deductible is met
    2. on the rest you pay a copay (fixed $) or coinsurance (%)
    3. your total is capped by what's left of the out-of-pocket maximum
"""

from dataclasses import asdict, dataclass, field


@dataclass
class CostRule:
    """How the policy says this specific service is cost-shared."""

    covered: bool = True
    deductible_applies: bool = True
    copay: float | None = None  # fixed dollars per visit/service
    coinsurance_percent: float | None = None  # e.g. 30 for 30%


@dataclass
class PlanCosts:
    deductible: float
    out_of_pocket_max: float


@dataclass
class CostEstimate:
    billed_amount: float
    you_pay: float
    plan_pays: float
    steps: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def estimate_cost(
    billed_amount: float,
    rule: CostRule,
    plan: PlanCosts,
    *,
    deductible_met: float = 0.0,
    out_of_pocket_met: float = 0.0,
) -> CostEstimate:
    if billed_amount < 0:
        raise ValueError("billed_amount must be >= 0")

    assumptions = [
        f"The {_money(billed_amount)} is the plan's allowed (in-network) amount for the service.",
        f"You have paid {_money(deductible_met)} toward your deductible and "
        f"{_money(out_of_pocket_met)} toward your out-of-pocket maximum so far this year.",
    ]

    if not rule.covered:
        return CostEstimate(
            billed_amount=billed_amount,
            you_pay=billed_amount,
            plan_pays=0.0,
            steps=[f"This service isn't covered, so you pay the full {_money(billed_amount)}.",
                   "Payments for non-covered services don't count toward your out-of-pocket maximum."],
            assumptions=assumptions[:1],
        )

    steps: list[str] = []
    remaining = billed_amount
    you_pay = 0.0

    if rule.deductible_applies:
        deductible_left = max(plan.deductible - deductible_met, 0.0)
        toward_deductible = min(remaining, deductible_left)
        if toward_deductible > 0:
            steps.append(
                f"Deductible: you pay the first {_money(toward_deductible)} "
                f"({_money(deductible_left)} of your {_money(plan.deductible)} deductible was left)."
            )
        else:
            steps.append("Deductible: already met, so cost-sharing starts right away.")
        you_pay += toward_deductible
        remaining -= toward_deductible
    else:
        steps.append("Deductible: doesn't apply to this service.")

    if remaining > 0:
        if rule.copay is not None:
            copay = min(rule.copay, remaining)
            steps.append(f"Copay: you pay {_money(copay)}; the plan pays the remaining {_money(remaining - copay)}.")
            you_pay += copay
        elif rule.coinsurance_percent is not None:
            share = remaining * rule.coinsurance_percent / 100
            steps.append(
                f"Coinsurance: you pay {rule.coinsurance_percent:g}% of the remaining {_money(remaining)} = {_money(share)}."
            )
            you_pay += share
        else:
            steps.append(f"The plan pays the remaining {_money(remaining)} in full.")

    oop_left = max(plan.out_of_pocket_max - out_of_pocket_met, 0.0)
    if you_pay > oop_left:
        steps.append(
            f"Out-of-pocket maximum: you only had {_money(oop_left)} left before hitting your "
            f"{_money(plan.out_of_pocket_max)} limit, so your share is capped there."
        )
        you_pay = oop_left

    you_pay = round(you_pay, 2)
    return CostEstimate(
        billed_amount=billed_amount,
        you_pay=you_pay,
        plan_pays=round(billed_amount - you_pay, 2),
        steps=steps,
        assumptions=assumptions,
    )
