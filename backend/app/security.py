"""Model-independent defenses against hostile documents and hostile output.

The red-team suite (redteam/) showed the model itself resisted most
injection attempts - but that is behaviour, not a guarantee, and it can
change with a different or newer model. These checks are plain code:

1. scan_for_injection   find instruction-like text aimed at an AI inside a
                        document, so it can be removed before the LLM sees it
2. redact_unsupported_contacts
                        phone numbers / links in an answer must appear in the
                        source excerpts, otherwise they're removed - the model
                        can't invent (or relay) a scam number or phishing link
3. ground_plan_facts    extracted dollar amounts must literally appear in the
                        document and make sense together
"""

import re
from dataclasses import dataclass

# Instruction-like phrases that have no business in an insurance policy.
# Each pattern is narrow on purpose: false positives would delete real policy text.
INJECTION_PATTERNS: list[tuple[str, str]] = [
    ("override", r"\b(ignore|disregard|forget)\b[^.]{0,40}\b(previous|prior|above|earlier|all)\b[^.]{0,20}\b(instructions?|rules|prompts?|exclusions?)"),
    ("addressed-to-ai", r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?(ai|assistant|chatbot|language model|llm|model)\b"),
    ("addressed-to-ai", r"^\s*(assistant|ai|system)\s*:"),
    ("role-change", r"\b(you are now|act as|pretend to be|switch to)\b[^.]{0,40}\b(mode|assistant|ai|model)\b"),
    ("system-override", r"\bsystem (override|prompt|instructions?|message)\b"),
    ("answer-steering", r"\b(when|before) answering\b|\bthe correct verdict\b|\b(always|must) tell the member\b"),
    ("prompt-extraction", r"\b(copy|print|repeat|reveal|output)\b[^.]{0,40}\b(system|your)\b[^.]{0,20}\b(instructions?|prompt|rules)\b"),
    ("credential-request", r"\b(card number|cvv|password|social security number|ssn|bank account|payment details)\b"),
]
_COMPILED = [(name, re.compile(p, re.IGNORECASE | re.MULTILINE)) for name, p in INJECTION_PATTERNS]


@dataclass
class InjectionFinding:
    rule: str
    line: str


def scan_for_injection(text: str) -> list[InjectionFinding]:
    findings = []
    for line in text.splitlines():
        for name, pattern in _COMPILED:
            if pattern.search(line):
                findings.append(InjectionFinding(rule=name, line=line.strip()))
                break
    return findings


def strip_injection(text: str) -> tuple[str, list[InjectionFinding]]:
    """Remove flagged lines. Lines are the unit because PDF text is line-based
    and an injected instruction usually sits on its own line(s)."""
    findings = scan_for_injection(text)
    if not findings:
        return text, []
    flagged = {f.line for f in findings}
    kept = [line for line in text.splitlines() if line.strip() not in flagged]
    return "\n".join(kept), findings


# ---------------------------------------------------------------------------
# Output: contact details must come from the sources
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|io|us|info|biz)\b(?:/[^\s<>()\"']*)?", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)[-10:]


def redact_unsupported_contacts(text: str, source_text: str) -> tuple[str, int]:
    """Replace phone numbers / URLs that don't appear in the source excerpts."""
    source_lower = source_text.lower()
    source_phones = {_digits(m.group()) for m in PHONE_RE.finditer(source_text)}
    removed = 0

    def phone(m: re.Match) -> str:
        nonlocal removed
        if _digits(m.group()) in source_phones:
            return m.group()
        removed += 1
        return "[phone number removed]"

    def url(m: re.Match) -> str:
        nonlocal removed
        if m.group().lower().rstrip(".,;") in source_lower:
            return m.group()
        removed += 1
        return "[link removed]"

    text = PHONE_RE.sub(phone, text)
    text = URL_RE.sub(url, text)
    return text, removed


# ---------------------------------------------------------------------------
# Plan facts: every number must be in the document
# ---------------------------------------------------------------------------

MONEY_FIELDS = (
    "deductible_individual", "deductible_family", "oop_max_individual", "oop_max_family",
    "primary_care_copay", "specialist_copay", "emergency_room_copay",
)
PERCENT_FIELDS = ("coinsurance_in_network_percent", "coinsurance_out_of_network_percent")


def _money_in_text(value: float, text: str) -> bool:
    n = int(value) if float(value).is_integer() else value
    candidates = {f"${n:,}", f"${n}", f"$ {n:,}", f"${float(value):,.2f}"}
    return any(c in text for c in candidates)


def ground_plan_facts(facts: dict | None, document_text: str) -> tuple[dict | None, list[str]]:
    """Null out numbers that don't appear in the document; drop inconsistent pairs."""
    if not facts:
        return facts, []
    facts = dict(facts)
    dropped: list[str] = []
    for key in MONEY_FIELDS:
        value = facts.get(key)
        if value is not None and (value < 0 or not _money_in_text(value, document_text)):
            facts[key] = None
            dropped.append(key)
    for key in PERCENT_FIELDS:
        value = facts.get(key)
        if value is not None and (not 0 <= value <= 100 or f"{int(value)}%" not in document_text):
            facts[key] = None
            dropped.append(key)
    for ded, oop in (("deductible_individual", "oop_max_individual"), ("deductible_family", "oop_max_family")):
        if facts.get(ded) is not None and facts.get(oop) is not None and facts[ded] > facts[oop]:
            facts[ded] = facts[oop] = None
            dropped += [ded, oop]
    return facts, dropped
