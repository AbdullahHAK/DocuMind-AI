"""Measure retrieval quality on the sample policy - no LLM, no API key, free to run.

Metrics
- hit@k : share of in-scope questions where an expected page is in the top-k policy chunks
- MRR   : mean reciprocal rank of the first correct chunk (1.0 = always ranked first)
- gate  : at each threshold, how many in-scope questions keep at least one chunk,
          and how many out-of-scope questions are blocked (so we can skip the LLM)

Run:  python eval/run_retrieval_eval.py
"""

from common import EVAL_DOC_ID, build_retriever, load_questions


def main() -> None:
    retriever = build_retriever()
    questions = load_questions()
    k = retriever.settings.policy_top_k
    rows = []
    for q in questions:
        # threshold=-inf: look at the raw ranking first; thresholds are applied in the sweep below
        result = retriever.retrieve(q["question"], EVAL_DOC_ID, threshold=float("-inf"))
        pages = [sc.chunk.page for sc in result.policy]
        scores = [sc.score for sc in result.policy]
        first_hit = next((i for i, p in enumerate(pages) if p in q["expected_pages"]), None)
        best = max([*scores, result.best_federal_score if result.best_federal_score is not None else -99.0])
        rows.append({
            **q,
            "pages": pages,
            "first_hit": first_hit,
            "best": best,
            "federal": [sc.chunk.source_title for sc in result.federal],
        })

    in_scope = [r for r in rows if not r.get("out_of_scope")]
    out_scope = [r for r in rows if r.get("out_of_scope")]

    print(f"\n{'id':22} {'hit@' + str(k):>6} {'rank':>5} {'best':>7}  top pages")
    for r in rows:
        hit = "-" if r.get("out_of_scope") else ("yes" if r["first_hit"] is not None else "MISS")
        rank = "" if r["first_hit"] is None else r["first_hit"] + 1
        print(f"{r['id']:22} {hit:>6} {rank!s:>5} {r['best']:7.2f}  {r['pages'][:k]}")

    hits = sum(r["first_hit"] is not None for r in in_scope)
    mrr = sum(1 / (r["first_hit"] + 1) for r in in_scope if r["first_hit"] is not None) / len(in_scope)
    print(f"\nhit@{k}: {hits}/{len(in_scope)} = {hits / len(in_scope):.0%}    MRR: {mrr:.2f}")

    fed_checks = [r for r in rows if r.get("expected_federal")]
    fed_ok = sum(any(t in r["federal"] for t in r["expected_federal"]) for r in fed_checks)
    print(f"federal source found: {fed_ok}/{len(fed_checks)}")

    current = retriever.settings.relevance_threshold
    print(f"\nRelevance gate sweep (current threshold = {current}):")
    print(f"{'threshold':>10} {'in-scope kept':>15} {'out-of-scope blocked':>22}")
    for t in (-8, -7, -6, -5, -4, -3, -2, -1, 0, 1):
        kept = sum(r["best"] >= t for r in in_scope)
        blocked = sum(r["best"] < t for r in out_scope)
        marker = "  <- current" if t == current else ""
        print(f"{t:>10} {kept:>8}/{len(in_scope):<6} {blocked:>12}/{len(out_scope):<9}{marker}")


if __name__ == "__main__":
    main()
