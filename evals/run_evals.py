"""Project 3, Phase 7: score the reviewer against cases with known answers.

Deterministic checks (verdict, findings) must always pass. AI checks (citations, forbidden
phrases, required mentions) and retrieval precision are measured, not assumed.

Usage:  python evals/run_evals.py            (live: Bedrock, about $0.01 total)
        python evals/run_evals.py --no-ai    (deterministic checks only, no AWS)
        python evals/run_evals.py --threshold 0.35   (try a different retrieval cutoff)
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import retrieve                                                    # noqa: E402
import review                                                      # noqa: E402
from plan_parser import load_plan, parse_changes                   # noqa: E402
from rules import BLOCK, evaluate                                   # noqa: E402
from tools import ToolBox                                          # noqa: E402

# Nova Lite on-demand prices (USD per 1M tokens) for a rough cost line in the report.
PRICE_IN, PRICE_OUT = 0.06, 0.24


def ai_text(r: dict) -> str:
    parts = [r.get("summary", "")]
    for e in r.get("explanations", []):
        parts += [e.get("why_it_matters", ""), e.get("suggestion", "")]
    return " ".join(parts).lower()


def run_case(case: dict, use_ai: bool) -> dict:
    changes = parse_changes(load_plan(ROOT / "tests" / "fixtures" / f"{case['fixture']}.json"))
    findings = evaluate(changes)
    verdict = "FAIL" if any(f.severity == BLOCK for f in findings) else "PASS"
    out = {"name": case["name"], "checks": {}, "notes": []}
    c = out["checks"]
    c["verdict"] = verdict == case["verdict"]
    c["findings"] = sorted(f.rule for f in findings) == sorted(case["rules"])

    embedder = None if use_ai else review.OfflineEmbedder()
    standards, rmetrics = retrieve.retrieve(changes, findings, embedder)
    related = [s["id"] for s in standards if s["matched_by"] != "rule"]
    allowed = set(case["related_allowed"])
    out["related"] = related
    out["top_scores"] = rmetrics["top_scores"]
    out["retrieval"] = rmetrics["retrieval"]
    out["related_ok"] = sum(1 for r in related if r in allowed)

    if not use_ai:
        return out
    payload = review.build_input(changes, findings, standards)
    box = ToolBox(changes)
    result, metrics = review.ask_model(payload, toolbox=box)
    out["metrics"] = {k: metrics.get(k) for k in ("input_tokens", "output_tokens", "tool_calls", "latency_ms")}
    c["ai_answered"] = result is not None
    if result is None:
        out["notes"].append(metrics.get("error", "no answer"))
        return out
    result = review.keep_known_addresses(result, findings, standards, box.looked_up)
    text = ai_text(result)
    expected_std = {retrieve.RULE_TO_STANDARD[f.rule] for f in findings}
    cited = {e.get("standard") for e in result["explanations"]} - {None}
    c["one_explanation_per_finding"] = len(result["explanations"]) == len(findings)
    c["cites_right_standard"] = expected_std <= cited
    c["required_mentions"] = all(m in text for m in case["must_mention"])
    bad = [p for p in case["must_not_say"] if p in text]
    c["no_forbidden_phrases"] = not bad
    if bad:
        out["notes"].append(f"said: {bad}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--threshold", type=float, help="override the embedding retrieval cutoff")
    args = ap.parse_args()
    if args.threshold is not None:
        retrieve.MIN_SCORE["embedding"] = args.threshold

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    results = []
    for i, case in enumerate(cases):
        results.append(run_case(case, use_ai=not args.no_ai))
        print(f"[{i + 1}/{len(cases)}] {case['name']}: "
              + ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in results[-1]["checks"].items()))
        if not args.no_ai:
            time.sleep(3)                 # stay well under the 20-per-minute embedding quota

    lines = ["# Evaluation report", "",
             f"Model: `{review.MODEL_ID if not args.no_ai else 'none (--no-ai)'}` · "
             f"retrieval cutoff: {retrieve.MIN_SCORE['embedding']} · cases: {len(cases)}", "",
             "| Case | " + " | ".join(sorted({k for r in results for k in r["checks"]})) + " | Related standards | Notes |",
             "|---|" + "---|" * (len({k for r in results for k in r["checks"]}) + 2)]
    keys = sorted({k for r in results for k in r["checks"]})
    for r in results:
        cells = ["✅" if r["checks"].get(k) else ("❌" if k in r["checks"] else "–") for k in keys]
        rel = ", ".join(r["related"]) or "none"
        lines.append(f"| {r['name']} | " + " | ".join(cells) + f" | {rel} ({r['related_ok']}/{len(r['related'])} relevant) | "
                     + "; ".join(r["notes"]) + " |")

    det = [r["checks"]["verdict"] and r["checks"]["findings"] for r in results]
    ai = [all(v for k, v in r["checks"].items() if k not in ("verdict", "findings")) for r in results
          if "ai_answered" in r["checks"]]
    shown = sum(len(r["related"]) for r in results)
    good = sum(r["related_ok"] for r in results)
    lines += ["", "## Summary", "",
              f"- Deterministic (verdict and findings): **{sum(det)}/{len(det)}**",
              f"- AI checks all passing: **{sum(ai)}/{len(ai)}**" if ai else "- AI checks: not run (--no-ai)",
              f"- Related-standard precision: **{good}/{shown}**" + (f" ({good / shown:.0%})" if shown else "")]
    if not args.no_ai:
        tin = sum(r["metrics"]["input_tokens"] or 0 for r in results if "metrics" in r)
        tout = sum(r["metrics"]["output_tokens"] or 0 for r in results if "metrics" in r)
        lines.append(f"- Tokens: {tin} in, {tout} out · estimated cost: ${tin * PRICE_IN / 1e6 + tout * PRICE_OUT / 1e6:.4f}")
    lines += ["", "## Retrieval scores (top 4 per case, for tuning the cutoff)", ""]
    lines += [f"- {r['name']} ({r['retrieval']}): " + ", ".join(f"{i} {s}" for i, s in r["top_scores"]) for r in results]

    report = ROOT / "evals" / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n" + "\n".join(lines[-(len(results) + 8):]))
    print(f"\nwrote {report.relative_to(ROOT)}")
    sys.exit(0 if all(det) else 1)


if __name__ == "__main__":
    main()
