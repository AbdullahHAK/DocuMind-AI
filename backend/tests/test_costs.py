import pytest

from app.costs import CostRule, PlanCosts, estimate_cost

PLAN = PlanCosts(deductible=3000, out_of_pocket_max=8500)  # the Evergreen sample plan
COINSURANCE_30 = CostRule(deductible_applies=True, coinsurance_percent=30)


def test_mri_before_deductible_is_paid_in_full():
    # Coverage example 10.3 in the sample policy: $1,800 MRI, nothing paid yet -> Sam pays $1,800
    est = estimate_cost(1800, COINSURANCE_30, PLAN)
    assert est.you_pay == 1800
    assert est.plan_pays == 0


def test_having_a_baby_matches_policy_coverage_example():
    # Coverage example 10.1: $12,700 -> $3,000 deductible + 30% of $9,700 = $5,910
    est = estimate_cost(12700, COINSURANCE_30, PLAN)
    assert est.you_pay == 5910
    assert est.plan_pays == 6790


def test_partially_met_deductible():
    est = estimate_cost(2000, COINSURANCE_30, PLAN, deductible_met=2500)
    # $500 deductible left, then 30% of $1,500 = $450
    assert est.you_pay == 950


def test_copay_without_deductible():
    est = estimate_cost(250, CostRule(deductible_applies=False, copay=60), PLAN)
    assert est.you_pay == 60
    assert est.plan_pays == 190


def test_copay_never_exceeds_the_bill():
    assert estimate_cost(40, CostRule(deductible_applies=False, copay=60), PLAN).you_pay == 40


def test_out_of_pocket_max_caps_the_total():
    est = estimate_cost(100_000, COINSURANCE_30, PLAN, out_of_pocket_met=8000)
    assert est.you_pay == 500
    assert any("out-of-pocket maximum" in s.lower() for s in est.steps)


def test_not_covered_means_you_pay_everything():
    est = estimate_cost(4000, CostRule(covered=False), PLAN)
    assert est.you_pay == 4000
    assert est.plan_pays == 0


def test_free_preventive_service():
    est = estimate_cost(300, CostRule(deductible_applies=False), PLAN)
    assert est.you_pay == 0


def test_negative_amount_is_rejected():
    with pytest.raises(ValueError):
        estimate_cost(-1, COINSURANCE_30, PLAN)
