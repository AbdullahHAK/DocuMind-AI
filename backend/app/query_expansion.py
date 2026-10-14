"""Bridge the vocabulary gap between how people talk and how policies are written.

People ask "is a nose job covered?"; the policy says "cosmetic surgery ...
to improve appearance". Neither embeddings nor BM25 reliably connect the two.
So before searching, we append the insurance terms that everyday phrases map
to. The original question is kept intact; expansion only *adds* words.

This is deterministic, free and testable - a deliberate alternative to asking
an LLM to rewrite every query (extra latency and cost on every question).
"""

import re

# (pattern matched against the lower-cased question, insurance terms to append)
LAY_TERMS: list[tuple[str, str]] = [
    (r"nose job|boob job|breast (augmentation|implants?)|face ?lift|tummy tuck|botox|liposuction|look(s)? better|appearance",
     "cosmetic surgery procedures to improve appearance"),
    (r"dentist|teeth|tooth|braces|cavity|cavities", "dental care"),
    (r"\bglasses\b|contact lens|contacts\b|eye exam|optometrist", "vision care eyeglasses eye exams"),
    (r"lasik|laser eye", "refractive eye surgery"),
    (r"check-?up|physical\b|wellness visit|screening", "preventive care annual physical exam"),
    (r"therap(y|ist) for (anxiety|depression|stress)|therapist|counsel(l)?ing|psychiatrist|psycholog|anxiety|depression",
     "mental health outpatient therapy"),
    (r"\ber\b|emergency room", "emergency room services"),
    (r"ambulance", "ambulance transport"),
    (r"abroad|overseas|vacation in|traveling in|travelling in|trip to|outside the (us|u\.s\.|united states)|foreign country",
     "care outside the United States emergency urgent care"),
    (r"fly me (back|home)|airlift|evacuat|bring me home", "medical evacuation repatriation"),
    (r"wegovy|ozempic|rybelsus|semaglutide", "GLP-1 semaglutide drugs"),
    (r"mounjaro|zepbound|tirzepatide|saxenda|liraglutide", "GLP-1 drugs"),
    (r"weight loss|lose weight|diet pills?|obesity", "weight management weight loss drugs"),
    (r"pregnan|baby|giving birth|deliver(y|ing)", "maternity newborn care"),
    (r"\bpt\b|physio", "physical therapy rehabilitation"),
    (r"chiropractor", "chiropractic care"),
    (r"hearing aid", "hearing aids"),
    (r"pre-?auth|precert|approval (first|before)|permission (first|before)", "prior authorization"),
    (r"surprise bill|balance bill|bill(ed)? (me )?extra|charge(d)? (me )?extra", "balance billing No Surprises Act"),
    (r"denied|denial|rejected|turned down", "claim denied appeal"),
    (r"\bkids?\b|\bson\b|daughter|\bchild", "dependent children eligibility"),
    (r"\bivf\b|fertility|getting pregnant", "infertility services"),
    (r"massage|naturopath|homeopath", "alternative medicine"),
    (r"nursing home|assisted living", "custodial long-term care"),
    (r"most i (could|would|can) pay|maximum i (pay|could pay)|worst case", "out-of-pocket maximum"),
    (r"medicine|meds\b|prescription|pharmacy", "prescription drugs tiers"),
]

_COMPILED = [(re.compile(pattern), terms) for pattern, terms in LAY_TERMS]


def expand_query(question: str) -> str:
    lowered = question.lower()
    additions: list[str] = []
    for pattern, terms in _COMPILED:
        if pattern.search(lowered) and terms not in additions:
            additions.append(terms)
    if not additions:
        return question
    return f"{question} ({'; '.join(additions)})"
