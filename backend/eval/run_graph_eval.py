"""Does the clause graph help? Retrieval-only, free to run (local models, no LLM).

For each multi-hop question, check whether EVERY required clause ends up in
the context sent to the LLM - first with graph expansion off, then on - and
measure how much time the expansion adds.

Run:  python eval/run_graph_eval.py
"""

import json
import statistics
import time
from pathlib import Path

from common import EVAL_DOC_ID, build_retriever

from app.graph import clause_key


def context_clauses(result) -> set[str]:
    return {clause_key(sc.chunk.section) for sc in result.policy}


def main() -> None:
    questions = json.loads((Path(__file__).parent / "multihop.json").read_text(encoding="utf-8"))["questions"]
    retriever = build_retriever()
    settings_on = retriever.settings
    settings_off = settings_on.model_copy(update={"graph_expansion": False})

    totals = {"off": 0, "on": 0}
    timings = {"off": [], "on": []}
    print(f"{'id':22} {'graph off':>10} {'graph on':>10}  missing without graph")
    for q in questions:
        row = {}
        for mode, settings in (("off", settings_off), ("on", settings_on)):
            retriever.settings = settings
            started = time.perf_counter()
            result = retriever.retrieve(q["question"], EVAL_DOC_ID)
            timings[mode].append((time.perf_counter() - started) * 1000)
            have = context_clauses(result)
            row[mode] = all(c in have for c in q["required_clauses"])
            row[f"missing_{mode}"] = [c for c in q["required_clauses"] if c not in have]
            totals[mode] += row[mode]
        print(f"{q['id']:22} {'all' if row['off'] else 'MISSING':>10} {'all' if row['on'] else 'MISSING':>10}  {row['missing_off']}")
    retriever.settings = settings_on

    n = len(questions)
    print(f"\nall required clauses in context: graph off {totals['off']}/{n} -> graph on {totals['on']}/{n}")
    print(f"median retrieval time: off {statistics.median(timings['off']):.0f} ms, on {statistics.median(timings['on']):.0f} ms")


if __name__ == "__main__":
    main()
