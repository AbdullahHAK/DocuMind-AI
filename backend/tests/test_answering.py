from types import SimpleNamespace

import anthropic
import httpx2 as httpx  # anthropic 1.x is built on httpx2
import pytest

from app.answering import AnswerError, AnswerService, compute_cost
from app.config import Settings
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


class FakeClient:
    """Stands in for anthropic.Anthropic: records the call, returns a canned response or raises."""

    def __init__(self, parsed=None, stop_reason="end_turn", error=None):
        self.calls = []
        self._parsed, self._stop, self._error = parsed, stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(
            parsed_output=self._parsed, stop_reason=self._stop,
            usage=SimpleNamespace(input_tokens=100, output_tokens=50), _request_id="req_test",
        )


def _service(client):
    return AnswerService(client, Settings())


def test_no_retrieval_returns_fallback_without_calling_llm():
    client = FakeClient()
    answer = _service(client).answer("pizza?", RetrievalResult())
    assert answer.verdict == "not_in_policy"
    assert answer.used_llm is False
    assert client.calls == []


def test_happy_path_returns_verified_answer():
    client = FakeClient(parsed=_llm_answer())
    answer = _service(client).answer("Do I need prior auth for an MRI?", _retrieval(), FACTS)
    assert answer.verdict == "covered_with_conditions"
    assert answer.citations[0].page == 5
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is LLMAnswer
    assert call["fallbacks"] == "default"
    assert "<excerpt id=\"P1\"" in call["messages"][0]["content"]


def test_cost_estimate_is_computed_in_python():
    rule = LLMCostRule(billed_amount=1800, deductible_met=None, covered=True, deductible_applies=True,
                       copay=None, coinsurance_percent=30)
    client = FakeClient(parsed=_llm_answer(cost_rule=rule))
    answer = _service(client).answer("MRI cost?", _retrieval(), FACTS)
    assert answer.cost_estimate.you_pay == 1800


def test_cost_skipped_without_amount_or_plan_facts():
    rule = LLMCostRule(billed_amount=None, deductible_met=None, covered=True, deductible_applies=True,
                       copay=None, coinsurance_percent=30)
    assert compute_cost(rule, FACTS) is None
    assert compute_cost(rule.model_copy(update={"billed_amount": 500}), None) is None


def test_refusal_becomes_friendly_error():
    with pytest.raises(AnswerError):
        _service(FakeClient(parsed=None, stop_reason="refusal")).answer("q", _retrieval())


def test_truncated_output_becomes_friendly_error():
    with pytest.raises(AnswerError, match="incomplete"):
        _service(FakeClient(parsed=None, stop_reason="max_tokens")).answer("q", _retrieval())


def test_rate_limit_becomes_friendly_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.RateLimitError("rate limited", response=response, body=None)
    with pytest.raises(AnswerError, match="busy"):
        _service(FakeClient(error=error)).answer("q", _retrieval())
