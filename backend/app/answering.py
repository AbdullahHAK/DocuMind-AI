"""Generate a grounded answer: retrieval result + question -> verified Answer.

Pipeline for one question:
  1. relevance gate failed?  -> fallback answer, no LLM call
  2. call Claude with structured output (the response must match LLMAnswer)
  3. verify citations against the source text, downgrade unsupported verdicts
  4. if the question is about cost, compute the estimate in Python
"""

import logging

import anthropic

from app.config import Settings
from app.costs import CostRule, PlanCosts, estimate_cost
from app.prompts import SYSTEM_PROMPT, build_user_message, source_ids
from app.retrieval import RetrievalResult
from app.schemas import Answer, CostEstimateOut, LLMAnswer, LLMCostRule
from app.verification import verify_citations

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnswerError(Exception):
    """Something went wrong talking to the LLM. The message is safe to show users."""


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
    def __init__(self, client: anthropic.Anthropic, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def _call_llm(self, question: str, retrieval: RetrievalResult, plan_facts: dict | None) -> LLMAnswer:
        try:
            response = self.client.beta.messages.parse(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                output_config={"effort": self.settings.llm_effort},
                # if a safety classifier declines, Anthropic retries on a fallback model server-side
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(question, retrieval, plan_facts)}],
                output_format=LLMAnswer,
            )
        except anthropic.AuthenticationError as exc:
            log.error("Anthropic authentication failed - check ANTHROPIC_API_KEY")
            raise AnswerError("The AI service isn't configured correctly. Please try again later.") from exc
        except anthropic.RateLimitError as exc:
            raise AnswerError("The AI service is busy right now. Please try again in a minute.") from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise AnswerError("Couldn't reach the AI service. Please try again.") from exc
        except anthropic.APIStatusError as exc:
            log.error("Anthropic API error %s: %s", exc.status_code, exc.message)
            raise AnswerError("The AI service returned an error. Please try again.") from exc

        log.info(
            "llm request_id=%s stop=%s in=%s out=%s",
            getattr(response, "_request_id", None), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            raise AnswerError("I can't help with that question. Try asking about what your policy covers.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise AnswerError("The answer came back incomplete. Please try asking again.")
        return response.parsed_output

    def answer(self, question: str, retrieval: RetrievalResult, plan_facts: dict | None = None) -> Answer:
        if not retrieval.found_anything:
            return fallback_answer()

        llm = self._call_llm(question, retrieval, plan_facts)
        policy_sources, federal_sources = source_ids(retrieval)
        verdict, citations, federal, warnings = verify_citations(llm, policy_sources, federal_sources)

        return Answer(
            verdict=verdict,
            headline=llm.headline,
            explanation=llm.explanation,
            citations=citations,
            conditions=llm.conditions,
            exclusions=llm.exclusions,
            federal=federal,
            questions_to_ask=llm.questions_to_ask,
            cost_estimate=compute_cost(llm.cost_rule, plan_facts),
            warnings=warnings,
        )
