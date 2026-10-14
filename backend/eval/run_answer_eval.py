"""End-to-end answer evaluation: retrieval + Claude + verification, scored
against the ground truth in questions.json.

Needs ANTHROPIC_API_KEY (backend/.env) and costs real money: roughly one
Claude call per question (~$0.02-0.05 each with the default model), so the
whole set is about $1. Use --limit to try a few first.

Metrics
- verdict exact     : verdict == expected_verdict
- verdict lenient   : same "direction" (covered + covered_with_conditions count
                      as one group; not_in_policy + unclear as another)
- citation on page  : at least one *verified* citation is on an expected page
- out-of-scope ok   : off-topic questions end as not_in_policy (gated or by the LLM)
- unverified quotes : citations the verifier had to throw away (hallucinated quotes)

Run:  python eval/run_answer_eval.py [--limit N]
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from common import EVAL_DOC_ID, SAMPLE_PDF, build_retriever, load_questions

from app.answering import AnswerError, AnswerService
from app.config import Settings
from app.services import build_llm_client

GROUPS = {
    "covered": "yes",
    "covered_with_conditions": "yes",
    "not_covered": "no",
    "unclear": "unknown",
    "not_in_policy": "unknown",
    "informational": "info",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    args = parser.parse_args()

    settings = Settings()
    client = build_llm_client(settings)
    if client is None:
        raise SystemExit("Set ANTHROPIC_API_KEY in backend/.env first.")
    retriever = build_retriever(settings)
    service = AnswerService(client, settings)
    facts = json.loads(SAMPLE_PDF.with_suffix(".facts.json").read_text(encoding="utf-8"))

    questions = load_questions()[: args.limit]
    rows = []
    for q in questions:
        started = time.perf_counter()
        retrieval = retriever.retrieve(q["question"], EVAL_DOC_ID)
        try:
            answer = service.answer(q["question"], retrieval, facts)
            error = None
        except AnswerError as exc:
            answer, error = None, str(exc)
        seconds = time.perf_counter() - started

        verdict = answer.verdict if answer else "error"
        pages = sorted({c.page for c in answer.citations if c.page}) if answer else []
        dropped = sum("couldn't be verified" in w for w in answer.warnings) if answer else 0
        row = {
            "id": q["id"],
            "question": q["question"],
            "expected": q["expected_verdict"],
            "verdict": verdict,
            "exact": verdict == q["expected_verdict"],
            "lenient": GROUPS.get(verdict) == GROUPS[q["expected_verdict"]],
            "cited_pages": pages,
            "page_hit": bool(set(pages) & set(q["expected_pages"])) if q["expected_pages"] else None,
            "used_llm": bool(answer and answer.used_llm),
            "unverified_dropped": dropped,
            "seconds": round(seconds, 1),
            "headline": answer.headline if answer else error,
            "out_of_scope": q.get("out_of_scope", False),
        }
        rows.append(row)
        mark = "ok " if row["exact"] else ("~  " if row["lenient"] else "XX ")
        print(f"{mark}{q['id']:22} expected={q['expected_verdict']:24} got={verdict:24} pages={pages} {seconds:.1f}s")

    in_scope = [r for r in rows if not r["out_of_scope"]]
    out_scope = [r for r in rows if r["out_of_scope"]]
    page_rows = [r for r in in_scope if r["page_hit"] is not None]
    summary = {
        "questions": len(rows),
        "verdict_exact": sum(r["exact"] for r in rows) / len(rows),
        "verdict_lenient": sum(r["lenient"] for r in rows) / len(rows),
        "citation_on_expected_page": sum(r["page_hit"] for r in page_rows) / len(page_rows) if page_rows else None,
        "out_of_scope_handled": sum(r["verdict"] == "not_in_policy" for r in out_scope) / len(out_scope) if out_scope else None,
        "llm_calls_skipped_by_gate": sum(not r["used_llm"] for r in rows),
        "unverified_citations_dropped": sum(r["unverified_dropped"] for r in rows),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
        "model": settings.llm_model,
        "effort": settings.llm_effort,
    }
    print("\n" + json.dumps(summary, indent=2))

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"answers-{stamp}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
