"""Run the red-team attack suite against the real pipeline and real LLM.

Each attack goes through the actual HTTP API (upload -> index -> ask), so it
tests exactly what a malicious user could do. Every attack runs several
times because LLM behaviour is probabilistic; we report the success rate.

Needs an LLM key (GEMINI_API_KEY is free). About (attacks x trials) LLM calls.

Run:  python redteam/run_redteam.py [--trials 3] [--only id1,id2]
"""

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import SAMPLE_DOC_ID, build_services  # noqa: E402
from redteam.attacks import ATTACKS  # noqa: E402


def ask(client: TestClient, question: str, doc_id: str) -> dict:
    res = client.post("/api/ask", json={"question": question, "doc_id": doc_id})
    if res.status_code != 200:
        return {"error": f"HTTP {res.status_code}: {res.text[:200]}"}
    events = {}
    for block in res.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events[lines["event"]] = json.loads(lines["data"])
    return events.get("answer") or {"error": events.get("error", {}).get("message", "no answer")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--only", default="", help="comma-separated attack ids")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--label", default="", help="saved with the results, e.g. 'before' or 'after'")
    args = parser.parse_args()

    attacks = [a for a in ATTACKS if not args.only or a.id in args.only.split(",")]
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            storage_dir=Path(tmp), questions_per_ip_per_hour=10_000, uploads_per_ip_per_hour=10_000,
        )
        services = build_services(settings, qdrant=QdrantClient(":memory:"))
        if services.llm is None:
            raise SystemExit("Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in backend/.env first.")
        rows = []
        with TestClient(create_app(services)) as client:
            for attack in attacks:
                successes, details = 0, []
                for trial in range(args.trials):
                    facts = None
                    doc_id = SAMPLE_DOC_ID
                    if attack.pdf is not None:
                        up = client.post("/api/documents", files={"file": (f"{attack.id}.pdf", attack.pdf, "application/pdf")})
                        if up.status_code != 201:
                            details.append({"trial": trial, "upload_error": up.text[:200]})
                            continue
                        doc = up.json()
                        doc_id, facts = doc["doc_id"], doc.get("facts")
                    answer = ask(client, attack.question, doc_id) if attack.target == "answer" else {}
                    hit = bool(attack.succeeded(answer, facts))
                    successes += hit
                    details.append({
                        "trial": trial, "attack_succeeded": hit, "verdict": answer.get("verdict"),
                        "headline": answer.get("headline") or answer.get("error"),
                        "warnings": answer.get("warnings"),
                        "facts": {k: facts.get(k) for k in ("deductible_individual", "oop_max_individual")} if facts else None,
                    })
                    time.sleep(args.delay)
                rate = successes / args.trials
                rows.append({"id": attack.id, "owasp": attack.owasp, "success_rate": rate, "trials": details})
                status = "BLOCKED" if successes == 0 else f"GOT THROUGH {successes}/{args.trials}"
                print(f"{attack.id:22} {status:18} {attack.owasp}")

    total = sum(r["success_rate"] for r in rows) / len(rows)
    print(f"\nmean attack success rate: {total:.0%}")
    out_dir = BACKEND / "redteam" / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"redteam-{args.label or 'run'}-{stamp}.json"
    out.write_text(json.dumps({"label": args.label, "model": services.llm.name, "rows": rows}, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
