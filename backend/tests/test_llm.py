"""Provider adapters: success path and the translation of every failure mode
into a user-safe LLMError. The SDK clients are faked; no network calls."""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx  # anthropic 1.x is built on httpx2
import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.config import Settings
from app.llm import AnthropicLLM, GeminiLLM, LLMError, build_llm, resolve_provider


class Out(BaseModel):
    verdict: str
    note: str | None


ARGS = dict(system="sys", user="question", schema=Out, max_tokens=100, effort="medium")


# ---------------------------------------------------------------- Gemini


def _gemini(text='{"verdict": "covered", "note": null}', finish="STOP", error=None, candidates=True,
            models=("gemini-test",), fail_models=()):
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] in fail_models:
            raise genai_errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        if error:
            raise error
        candidate = SimpleNamespace(finish_reason=SimpleNamespace(name=finish))
        return SimpleNamespace(
            text=text,
            candidates=[candidate] if candidates else [],
            usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
        )

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiLLM(client, list(models)), calls


def test_gemini_returns_validated_object_and_sends_json_schema():
    llm, calls = _gemini()
    assert llm.generate(**ARGS) == Out(verdict="covered", note=None)
    config = calls[0]["config"]
    assert calls[0]["model"] == "gemini-test"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["verdict"]["type"] == "string"
    assert config.system_instruction == "sys"


@pytest.mark.parametrize(
    ("code", "match"),
    [(429, "busy"), (403, "configured"), (400, "rephrasing")],
)
def test_gemini_client_errors(code, match):
    llm, _ = _gemini(error=genai_errors.ClientError(code, {"error": {"message": "x", "status": "X"}}))
    with pytest.raises(LLMError, match=match):
        llm.generate(**ARGS)


def test_gemini_server_error_on_every_model():
    llm, calls = _gemini(error=genai_errors.ServerError(503, {"error": {"message": "down", "status": "UNAVAILABLE"}}),
                         models=("a", "b"))
    with pytest.raises(LLMError, match="overloaded"):
        llm.generate(**ARGS)
    assert [c["model"] for c in calls] == ["a", "b"]


def test_gemini_falls_back_to_next_model_when_overloaded():
    llm, calls = _gemini(models=("big", "lite"), fail_models=("big",))
    assert llm.generate(**ARGS).verdict == "covered"
    assert [c["model"] for c in calls] == ["big", "lite"]


def test_gemini_timeout_falls_back():
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "slow":
            raise TimeoutError("read timed out")
        return SimpleNamespace(text='{"verdict": "covered", "note": null}',
                               candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
                               usage_metadata=None)

    llm = GeminiLLM(SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), ["slow", "fast"])
    assert llm.generate(**ARGS).verdict == "covered"
    assert calls == ["slow", "fast"]


def test_gemini_non_retryable_error_does_not_try_other_models():
    llm, calls = _gemini(error=genai_errors.ClientError(400, {"error": {"message": "bad", "status": "INVALID"}}),
                         models=("a", "b"))
    with pytest.raises(LLMError):
        llm.generate(**ARGS)
    assert len(calls) == 1


@pytest.mark.parametrize(("finish", "match"), [("MAX_TOKENS", "incomplete"), ("SAFETY", "can't help")])
def test_gemini_bad_finish_reasons(finish, match):
    llm, _ = _gemini(finish=finish)
    with pytest.raises(LLMError, match=match):
        llm.generate(**ARGS)


def test_gemini_blocked_prompt_has_no_candidates():
    llm, _ = _gemini(candidates=False)
    with pytest.raises(LLMError, match="can't help"):
        llm.generate(**ARGS)


def test_gemini_json_that_breaks_the_schema():
    llm, _ = _gemini(text='{"wrong": 1}')
    with pytest.raises(LLMError, match="unexpected format"):
        llm.generate(**ARGS)


# ---------------------------------------------------------------- Anthropic


def _anthropic(parsed=None, stop="end_turn", error=None):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return SimpleNamespace(parsed_output=parsed, stop_reason=stop,
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1), _request_id="req")

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    return AnthropicLLM(client, "claude-test"), calls


def test_anthropic_success_uses_structured_output_and_fallbacks():
    llm, calls = _anthropic(parsed=Out(verdict="covered", note=None))
    assert llm.generate(**ARGS).verdict == "covered"
    assert calls[0]["output_format"] is Out
    assert calls[0]["fallbacks"] == "default"


@pytest.mark.parametrize(("stop", "match"), [("refusal", "can't help"), ("max_tokens", "incomplete")])
def test_anthropic_bad_stop_reasons(stop, match):
    llm, _ = _anthropic(parsed=None, stop=stop)
    with pytest.raises(LLMError, match=match):
        llm.generate(**ARGS)


def test_anthropic_rate_limit():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    llm, _ = _anthropic(error=anthropic.RateLimitError("rate limited", response=response, body=None))
    with pytest.raises(LLMError, match="busy"):
        llm.generate(**ARGS)


# ---------------------------------------------------------------- provider choice


def test_provider_resolution():
    assert resolve_provider(Settings(llm_provider=None, gemini_api_key="g", anthropic_api_key="a")) == "gemini"
    assert resolve_provider(Settings(llm_provider=None, gemini_api_key=None, anthropic_api_key="a")) == "anthropic"
    assert resolve_provider(Settings(llm_provider="anthropic", gemini_api_key="g", anthropic_api_key="a")) == "anthropic"
    assert resolve_provider(Settings(llm_provider=None, gemini_api_key=None, anthropic_api_key=None)) is None


def test_build_llm_without_keys_returns_none():
    assert build_llm(Settings(llm_provider=None, gemini_api_key=None, anthropic_api_key=None)) is None


def test_build_llm_gemini():
    llm = build_llm(Settings(llm_provider="gemini", gemini_api_key="fake-key", gemini_model="gemini-x",
                             gemini_fallback_models=["gemini-y", "gemini-x"]))
    assert isinstance(llm, GeminiLLM) and llm.name == "gemini:gemini-x"
    assert llm.models == ["gemini-x", "gemini-y"]  # primary first, no duplicates
