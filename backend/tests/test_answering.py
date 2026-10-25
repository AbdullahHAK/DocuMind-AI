import pytest

from app.answering import AnswerError, AnswerService, compute_cost
from app.config import Settings
from app.llm import LLMError
from app.models import Chunk
from app.retrieval import RetrievalResult, ScoredChunk
from app.schemas import LLMAnswer, LLMCostRule, LLMPolicyCitation

FACTS = {"deductible_individual": 3000, "oop_max_individual": 8500}
MRI_TEXT = "Advanced imaging (MRI, CT, PET): In-Network 30% coinsurance after deductible. Prior Authorization is required."


def _retrieval():
    chunk = Chunk("c", "d", "policy", MRI_TEXT, 0, "Policy", page=5, section="3.4 Imaging")
    return RetrievalResult(policy=[ScoredChunk(chunk, 4.0)])


def _llm_answer(**overrides):
    data = dict(
        verdict="covered_with_conditions", headline="Yes, with prior authorization.", explanation="...",
        policy_citations=[LLMPolicyCitation(source_id="P1", quote="Prior Authorization is required.")],
        conditions=["Prior authorization"], exclusions=[], federal_notes=[], questions_to_ask=["Is it in-network?"],
        cost_rule=None,
    )
    data.update(overrides)
    return LLMAnswer(**data)


class FakeLLM:
    """Implements the StructuredLLM interface: records calls, returns a canned answer or raises."""

    name = "fake"

    def __init__(self, parsed=None, error=None):
        self.calls = []
        self._parsed, self._error = parsed, error

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._parsed


def _service(llm):
    return AnswerService(llm, Settings())


def test_no_retrieval_returns_fallback_without_calling_llm():
    llm = FakeLLM()
    answer = _service(llm).answer("pizza?", RetrievalResult())
    assert answer.verdict == "not_in_policy"
    assert answer.used_llm is False
    assert llm.calls == []


def test_happy_path_returns_verified_answer():
    llm = FakeLLM(parsed=_llm_answer())
    answer = _service(llm).answer("Do I need prior auth for an MRI?", _retrieval(), FACTS)
    assert answer.verdict == "covered_with_conditions"
    assert answer.citations[0].page == 5
    call = llm.calls[0]
    assert call["schema"] is LLMAnswer
    assert call["effort"] == "medium"
    assert '<excerpt id="P1"' in call["user"]


def test_cost_estimate_is_computed_in_python():
    rule = LLMCostRule(billed_amount=1800, deductible_met=None, covered=True, deductible_applies=True,
                       copay=None, coinsurance_percent=30)
    answer = _service(FakeLLM(parsed=_llm_answer(cost_rule=rule))).answer("MRI cost?", _retrieval(), FACTS)
    assert answer.cost_estimate.you_pay == 1800


def test_cost_skipped_without_amount_or_plan_facts():
    rule = LLMCostRule(billed_amount=None, deductible_met=None, covered=True, deductible_applies=True,
                       copay=None, coinsurance_percent=30)
    assert compute_cost(rule, FACTS) is None
    assert compute_cost(rule.model_copy(update={"billed_amount": 500}), None) is None


def test_llm_errors_propagate_as_answer_errors():
    assert AnswerError is LLMError
    with pytest.raises(AnswerError, match="busy"):
        _service(FakeLLM(error=LLMError("busy"))).answer("q", _retrieval())
