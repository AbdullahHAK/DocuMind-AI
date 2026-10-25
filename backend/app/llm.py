"""LLM providers behind one tiny interface.

The rest of the app only ever asks: "here is a system prompt, a user message
and a Pydantic schema - give me back a validated object of that schema".
Two implementations:

- GeminiLLM     Google Gemini (free tier available) - the default
- AnthropicLLM  Anthropic Claude

Each one translates provider-specific failures (rate limits, auth errors,
safety blocks, truncated output) into LLMError with a message that is safe to
show to users. Swapping providers is a config change: LLM_PROVIDER.
"""

import logging
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Something went wrong talking to the LLM. The message is safe to show users."""


class StructuredLLM(Protocol):
    name: str

    def generate(
        self, *, system: str, user: str, schema: type[T], max_tokens: int, effort: str, meta: dict | None = None
    ) -> T:
        """meta, if given, is filled with {"model", "input_tokens", "output_tokens"} for tracing."""
        ...


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


class GeminiLLM:
    """Tries each model in order; moves on when one is overloaded or out of quota.

    Free-tier Gemini models are frequently overloaded (503/504) and each model
    has its own rate limit, so a fallback model keeps the app answering.
    """

    RETRYABLE = {429, 500, 503, 504}

    def __init__(self, client, models: list[str]) -> None:
        self.client = client  # google.genai.Client
        self.models = models
        self.name = f"gemini:{models[0]}"

    def generate(
        self, *, system: str, user: str, schema: type[T], max_tokens: int, effort: str, meta: dict | None = None
    ) -> T:
        from google.genai import errors, types

        levels = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            # JSON mode + schema: Gemini must answer with JSON matching our Pydantic model
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            thinking_config=types.ThinkingConfig(thinking_level=levels.get(effort, "MEDIUM")),
        )
        last_error: Exception | None = None
        for model in self.models:
            try:
                response = self.client.models.generate_content(model=model, contents=user, config=config)
            except errors.APIError as exc:
                if exc.code in self.RETRYABLE:
                    log.warning("Gemini %s unavailable (%s), trying next model", model, exc.code)
                    last_error = exc
                    continue
                if exc.code in (401, 403):
                    log.error("Gemini rejected the API key - check GEMINI_API_KEY")
                    raise LLMError("The AI service isn't configured correctly. Please try again later.") from exc
                log.error("Gemini error %s: %s", exc.code, exc.message)
                raise LLMError("The AI service rejected the request. Please try rephrasing your question.") from exc
            except Exception as exc:  # timeouts and network errors from the HTTP layer
                log.warning("Gemini %s request failed (%s), trying next model", model, type(exc).__name__)
                last_error = exc
                continue
            if meta is not None:
                usage = response.usage_metadata
                meta.update(
                    model=f"gemini:{model}",
                    input_tokens=getattr(usage, "prompt_token_count", None),
                    output_tokens=getattr(usage, "candidates_token_count", None),
                    fallbacks_used=self.models.index(model),
                )
            return self._parse(response, schema, model)

        if isinstance(last_error, errors.APIError) and last_error.code == 429:
            raise LLMError("The AI service is busy right now (free-tier limit). Please try again in a minute.") from last_error
        raise LLMError("The AI service is overloaded right now. Please try again in a minute.") from last_error

    def _parse(self, response, schema: type[T], model: str) -> T:
        usage = response.usage_metadata
        candidate = response.candidates[0] if response.candidates else None
        finish = candidate.finish_reason.name if candidate and candidate.finish_reason else None
        log.info(
            "llm=gemini:%s finish=%s in=%s out=%s", model, finish,
            getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None),
        )
        if candidate is None or finish in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}:
            raise LLMError("I can't help with that question. Try asking about what your policy covers.")
        if finish == "MAX_TOKENS":
            raise LLMError("The answer came back incomplete. Please try asking again.")
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            log.warning("Gemini returned JSON that doesn't match the schema: %s", exc)
            raise LLMError("The answer came back in an unexpected format. Please try again.") from exc


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------


class AnthropicLLM:
    def __init__(self, client, model: str) -> None:
        self.client = client  # anthropic.Anthropic
        self.model = model
        self.name = f"anthropic:{model}"

    def generate(
        self, *, system: str, user: str, schema: type[T], max_tokens: int, effort: str, meta: dict | None = None
    ) -> T:
        import anthropic

        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                output_config={"effort": effort},
                # if a safety classifier declines, Anthropic retries on a fallback model server-side
                betas=[ANTHROPIC_FALLBACK_BETA],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.AuthenticationError as exc:
            log.error("Anthropic authentication failed - check ANTHROPIC_API_KEY")
            raise LLMError("The AI service isn't configured correctly. Please try again later.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("The AI service is busy right now. Please try again in a minute.") from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise LLMError("Couldn't reach the AI service. Please try again.") from exc
        except anthropic.APIStatusError as exc:
            log.error("Anthropic API error %s: %s", exc.status_code, exc.message)
            raise LLMError("The AI service returned an error. Please try again.") from exc

        log.info(
            "llm=%s request_id=%s stop=%s in=%s out=%s", self.name, getattr(response, "_request_id", None),
            response.stop_reason, response.usage.input_tokens, response.usage.output_tokens,
        )
        if meta is not None:
            meta.update(model=f"anthropic:{response.model}", input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens, fallbacks_used=0)
        if response.stop_reason == "refusal":
            raise LLMError("I can't help with that question. Try asking about what your policy covers.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("The answer came back incomplete. Please try asking again.")
        return response.parsed_output


# ---------------------------------------------------------------------------


def resolve_provider(settings: Settings) -> str | None:
    """Explicit LLM_PROVIDER wins; otherwise use whichever API key is present."""
    if settings.llm_provider:
        return settings.llm_provider
    if settings.gemini_api_key:
        return "gemini"
    if settings.anthropic_api_key:
        return "anthropic"
    return None


def build_llm(settings: Settings) -> StructuredLLM | None:
    provider = resolve_provider(settings)
    if provider == "gemini" and settings.gemini_api_key:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=settings.gemini_api_key,
            # fail fast: one retry, hard timeout - then GeminiLLM falls back to the next model
            http_options=types.HttpOptions(
                timeout=settings.llm_timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1.0, max_delay=4.0),
            ),
        )
        models = [settings.gemini_model, *[m for m in settings.gemini_fallback_models if m != settings.gemini_model]]
        return GeminiLLM(client, models)
    if provider == "anthropic" and settings.anthropic_api_key:
        import anthropic

        return AnthropicLLM(anthropic.Anthropic(api_key=settings.anthropic_api_key), settings.anthropic_model)
    log.warning("No LLM API key set (GEMINI_API_KEY or ANTHROPIC_API_KEY): retrieval works, answers don't.")
    return None
