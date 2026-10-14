from types import SimpleNamespace

from app.config import Settings
from app.ingest.pdf import Page
from app.plan_facts import PlanFacts, document_head, extract_plan_facts


def test_document_head_truncates_and_labels_pages():
    pages = [Page(1, "a" * 60), Page(2, "b" * 60), Page(3, "c" * 60)]
    head = document_head(pages, max_chars=100)
    assert head.startswith("[page 1]")
    assert len(head) <= 110
    assert "c" not in head


def _client(parsed, stop="end_turn"):
    def parse(**kwargs):
        return SimpleNamespace(parsed_output=parsed, stop_reason=stop)
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))


def test_extract_returns_dict():
    facts = PlanFacts(
        plan_name="X", insurer=None, plan_type="PPO", plan_year="2026", deductible_individual=3000,
        deductible_family=None, oop_max_individual=8500, oop_max_family=None, coinsurance_in_network_percent=30,
        coinsurance_out_of_network_percent=None, primary_care_copay=30, specialist_copay=None, emergency_room_copay=None,
    )
    out = extract_plan_facts(_client(facts), Settings(), [Page(1, "text")])
    assert out["deductible_individual"] == 3000


def test_extract_failure_is_non_fatal():
    assert extract_plan_facts(_client(None, stop="refusal"), Settings(), [Page(1, "text")]) is None
