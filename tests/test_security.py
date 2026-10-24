"""Phase 7 security tests: injection and secrets can't reach the model or the PR comment."""
import importlib.util
import json
from pathlib import Path

from plan_parser import Change, load_plan, parse_changes
from review import build_input, render
from rules import evaluate
from tools import ToolBox

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def everything_the_model_could_see(name):
    changes = parse_changes(load_plan(FIXTURES / f"{name}.json"))
    findings = evaluate(changes)
    payload = build_input(changes, findings, [])
    box = ToolBox(changes)
    tool_outputs = [box.run("get_change", {"address": c.address})[0] for c in changes]
    comment = render(findings, len(changes), None, {"model": "fake"}, [])
    return findings, json.dumps(payload) + json.dumps(tool_outputs), comment


def test_injected_text_in_values_never_reaches_the_model():
    findings, seen, comment = everything_the_model_could_see("prompt_injection")
    assert "ignore all previous instructions" not in seen.lower()     # tag, description, rule description
    assert "ignore all previous instructions" not in comment.lower()


def test_injection_in_a_resource_name_cannot_change_the_verdict():
    findings, _, comment = everything_the_model_could_see("prompt_injection")
    assert "FAIL" in comment and findings[0].rule == "ADMIN_PORT_OPEN_TO_WORLD"


def test_secrets_never_reach_the_model_or_the_comment():
    _, seen, comment = everything_the_model_could_see("secret_in_values")
    for secret in ("SuperSecret-999", "OldSecret-111"):
        assert secret not in seen and secret not in comment
    assert "password" in seen        # the model may know *that* it changed, never *what* it is


def test_backticks_and_pipes_in_addresses_cannot_break_the_comment():
    nasty = 'aws_s3_bucket.b["x`| injected | ` **bold**"]'
    c = Change(nasty, "aws_s3_bucket", "delete", {"bucket": "b"}, None)
    comment = render(evaluate([c]), 1, None, {"model": "fake"}, [])
    row = [line for line in comment.splitlines() if "STATEFUL_DESTROY" in line][0]
    assert row.count("`") == 4 and row.count("|") == 6      # rule and address code spans, 5 columns


def test_every_eval_case_passes_its_deterministic_checks():
    spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run_evals.py")
    run_evals = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_evals)
    for case in json.loads((ROOT / "evals" / "cases.json").read_text()):
        result = run_evals.run_case(case, use_ai=False)
        assert result["checks"] == {"verdict": True, "findings": True}, case["name"]
