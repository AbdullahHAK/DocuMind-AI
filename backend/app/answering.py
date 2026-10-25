"""Generate a grounded answer: retrieval result + question -> verified Answer.

Pipeline for one question:
  1. relevance gate failed?  -> fallback answer, no LLM call
  2. call the LLM with structured output (the response must match LLMAnswer)
  3. verify citations against the source text, downgrade unsupported verdicts
  4. if the question is about cost, compute the estimate in Python
"""

from app.config import Settings
from app.costs import CostRule, PlanCosts, estimate_cost
from app.llm import LLMError, StructuredLLM
from app.prompts import SYSTEM_PROMPT, build_user_message, source_ids
from app.security import redact_unsupported_contacts
from app.retrieval import RetrievalResult
from app.schemas import Answer, CostEstimateOut, LLMAnswer, LLMCostRule
from app.verification import verify_citations

# Kept as the name the API layer catches; raised by any LLM provider.
AnswerError = LLMError


def fallback_answer() -> Answer:
    return Answer(
        verdict="not_in_policy",
        headline="I couldn't find anything about this in your policy.",
        explanation=(
            "None of the sections I searched in your policy discuss this. That doesn't always mean it isn't "
            "covered - it may be described under a different name, or in a document I don't have, such as a "
            "drug formulary or provider directory. Please check with your insurer before relying on it."
        ),
        questions_to_ask=[
            "Is this service covered under my plan, and under which section of my policy?",
            "Does it need prior authorization or a referral?",
            "What will I pay in-network versus out-of-network?",
        ],
        used_llm=False,
    )


def plan_costs_from_facts(facts: dict | None) -> PlanCosts | None:
    if not facts:
        return None
    deductible, oop = facts.get("deductible_individual"), facts.get("oop_max_individual")
    if deductible is None or oop is None:
        return None
    return PlanCosts(deductible=float(deductible), out_of_pocket_max=float(oop))


def compute_cost(rule: LLMCostRule | None, facts: dict | None) -> CostEstimateOut | None:
    plan = plan_costs_from_facts(facts)
    if rule is None or rule.billed_amount is None or rule.billed_amount <= 0 or plan is None:
        return None
    estimate = estimate_cost(
        rule.billed_amount,
        CostRule(
            covered=rule.covered,
            deductible_applies=rule.deductible_applies,
            copay=rule.copay,
            coinsurance_percent=rule.coinsurance_percent,
        ),
        plan,
        deductible_met=max(rule.deductible_met or 0.0, 0.0),
    )
    return CostEstimateOut(**estimate.to_dict())


class AnswerService:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    def _call_llm(self, question: str, retrieval: RetrievalResult, plan_facts: dict | None) -> LLMAnswer:
        return self.llm.generate(
            system=SYSTEM_PROMPT,
            user=build_user_message(question, retrieval, plan_facts),
            schema=LLMAnswer,
            max_tokens=self.settings.llm_max_tokens,
            effort=self.settings.llm_effort,
        )

    def answer(self, question: str, retrieval: RetrievalResult, plan_facts: dict | None = None) -> Answer:
        if not retrieval.found_anything:
            return fallback_answer()

        llm = self._call_llm(question, retrieval, plan_facts)
        policy_sources, federal_sources = source_ids(retrieval)
        verdict, citations, federal, warnings = verify_citations(llm, policy_sources, federal_sources)

        if llm.conflicting_provisions:
            warnings.append(f"Your policy text seems to contradict itself: {llm.conflicting_provisions} "
                            "Ask your insurer which provision applies.")
            if verdict in ("covered", "covered_with_conditions", "not_covered"):
                verdict = "unclear"

        # Contact details in free-text fields must come from the excerpts the model was given.
        source_text = "\n".join(sc.chunk.text for sc in [*retrieval.policy, *retrieval.federal])
        removed = 0

        def clean(text: str) -> str:
            nonlocal removed
            text, n = redact_unsupported_contacts(text, source_text)
            removed += n
            return text

        answer = Answer(
            verdict=verdict,
            headline=clean(llm.headline),
            explanation=clean(llm.explanation),
            citations=citations,
            conditions=[clean(c) for c in llm.conditions],
            exclusions=[clean(e) for e in llm.exclusions],
            federal=[f.model_copy(update={"note": clean(f.note)}) for f in federal],
            questions_to_ask=[clean(q) for q in llm.questions_to_ask],
            cost_estimate=compute_cost(llm.cost_rule, plan_facts),
            warnings=warnings,
        )
        if removed:
            answer.warnings.append(f"Removed {removed} phone number(s) or link(s) that don't appear in your policy.")
        return answer
