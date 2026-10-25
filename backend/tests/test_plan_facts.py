from app.ingest.pdf import Page
from app.llm import LLMError
from app.plan_facts import PlanFacts, document_head, extract_plan_facts


def test_document_head_truncates_and_labels_pages():
    pages = [Page(1, "a" * 60), Page(2, "b" * 60), Page(3, "c" * 60)]
    head = document_head(pages, max_chars=100)
    assert head.startswith("[page 1]")
    assert len(head) <= 110
    assert "c" not in head


class FakeLLM:
    name = "fake"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def test_extract_returns_dict():
    facts = PlanFacts(**{f: None for f in PlanFacts.model_fields} | {"deductible_individual": 3000, "plan_type": "PPO"})
    llm = FakeLLM(result=facts)
    out = extract_plan_facts(llm, [Page(1, "text")])
    assert out["deductible_individual"] == 3000
    assert llm.calls[0]["schema"] is PlanFacts
    assert llm.calls[0]["effort"] == "low"


def test_extract_failure_is_non_fatal():
    assert extract_plan_facts(FakeLLM(error=LLMError("busy")), [Page(1, "text")]) is None
