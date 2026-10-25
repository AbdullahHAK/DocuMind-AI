"""Pydantic models for (1) what the LLM must return and (2) what the API returns.

Keeping them separate is deliberate: the LLM output is *untrusted* - it gets
verified (citations checked against the source text, cost math redone in
Python) before it becomes an API answer.
"""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal[
    "covered",  # the policy clearly covers it
    "covered_with_conditions",  # covered, but with prior auth / limits / cost-sharing caveats
    "not_covered",  # the policy clearly excludes it
    "unclear",  # the policy text is ambiguous or contradictory
    "not_in_policy",  # the excerpts don't address the question
    "informational",  # not a coverage question (e.g. "what is my deductible?")
]


# ---------------------------------------------------------------------------
# 1. Structured output the LLM must produce
# ---------------------------------------------------------------------------


class LLMPolicyCitation(BaseModel):
    source_id: str = Field(description="ID of the policy excerpt, e.g. 'P2'.")
    quote: str = Field(description="Words copied exactly from that excerpt, at most ~30 words.")


class LLMFederalNote(BaseModel):
    source_id: str = Field(description="ID of the federal excerpt, e.g. 'F1'.")
    note: str = Field(description="One or two sentences on how this federal rule applies to the question.")


class LLMCostRule(BaseModel):
    billed_amount: float | None = Field(description="Dollar amount for the service if the user stated one, else null.")
    deductible_met: float | None = Field(description="Amount already paid toward the deductible if the user stated it, else null.")
    covered: bool
    deductible_applies: bool = Field(description="True if the policy says the deductible applies to this service.")
    copay: float | None = Field(description="Fixed copay in dollars from the policy, else null.")
    coinsurance_percent: float | None = Field(description="Coinsurance percent from the policy (30 for 30%), else null.")


class LLMAnswer(BaseModel):
    verdict: Verdict
    headline: str = Field(description="One plain-English sentence that directly answers the question.")
    explanation: str = Field(description="2-5 sentences explaining the answer, under 120 words.")
    policy_citations: list[LLMPolicyCitation]
    conditions: list[str] = Field(description="Requirements that must be met, e.g. prior authorization, visit limits.")
    exclusions: list[str] = Field(description="Relevant things the policy does NOT cover.")
    federal_notes: list[LLMFederalNote]
    questions_to_ask: list[str] = Field(description="2-4 specific questions to ask the insurer or provider.")
    conflicting_provisions: str | None = Field(
        description="If excerpts contradict each other on this question, describe the conflict in one sentence. Otherwise null."
    )
    cost_rule: LLMCostRule | None = Field(description="Only when the question is about cost and the policy states the cost-sharing.")


# ---------------------------------------------------------------------------
# 2. What the API returns to the frontend
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    source_id: str
    quote: str
    page: int | None
    section: str | None


class FederalReference(BaseModel):
    source_id: str
    note: str
    title: str
    url: str | None


class CostEstimateOut(BaseModel):
    billed_amount: float
    you_pay: float
    plan_pays: float
    steps: list[str]
    assumptions: list[str]


class Answer(BaseModel):
    verdict: Verdict
    headline: str
    explanation: str
    citations: list[Citation] = []
    conditions: list[str] = []
    exclusions: list[str] = []
    federal: list[FederalReference] = []
    questions_to_ask: list[str] = []
    cost_estimate: CostEstimateOut | None = None
    warnings: list[str] = []
    used_llm: bool = True


class SourcePreview(BaseModel):
    """A retrieved chunk, sent to the UI before the answer is ready."""

    source_id: str
    kind: Literal["policy", "federal"]
    page: int | None
    section: str | None
    title: str
    url: str | None
    text: str
    score: float


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    doc_id: str = Field(min_length=1, max_length=64)
