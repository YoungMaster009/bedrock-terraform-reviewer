"""Phase 4 tests: the AI can explain, but it can never change the verdict or invent resources."""
import json
from pathlib import Path

from plan_parser import load_plan, parse_changes
from review import ask_model, build_input, keep_known_addresses, parse_model_json, render
from rules import evaluate

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Stands in for boto3's bedrock-runtime client, so tests cost nothing and need no AWS."""
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "usage": {"inputTokens": 100, "outputTokens": 50}}


def setup(name):
    changes = parse_changes(load_plan(FIXTURES / f"{name}.json"))
    findings = evaluate(changes)
    return changes, findings, build_input(changes, findings)


def test_model_sees_attribute_names_but_never_values():
    _, _, payload = setup("update_tags")
    text = json.dumps(payload)
    assert "tags" in text
    assert "platform" not in text and "ops" not in text     # the tag values stay out


def test_good_model_output_is_used():
    _, findings, payload = setup("delete_database")
    reply = json.dumps({"summary": "Deletes the database.", "explanations": [
        {"address": "aws_db_instance.main", "why_it_matters": "Data loss.", "suggestion": "Snapshot first."}]})
    review, metrics = ask_model(payload, FakeClient(reply))
    assert review["summary"] == "Deletes the database."
    assert metrics["input_tokens"] == 100


def test_fenced_json_is_tolerated():
    assert parse_model_json('```json\n{"summary": "s", "explanations": []}\n```')["summary"] == "s"


def test_garbage_output_falls_back_without_crashing():
    _, _, payload = setup("delete_database")
    review, metrics = ask_model(payload, FakeClient("I think this looks fine!"))
    assert review is None and "error" in metrics


def test_bedrock_error_falls_back_without_crashing():
    _, _, payload = setup("delete_database")
    review, metrics = ask_model(payload, FakeClient(error=RuntimeError("AccessDenied")))
    assert review is None and "AccessDenied" in metrics["error"]


def test_hallucinated_addresses_are_dropped():
    _, findings, _ = setup("delete_database")
    review = {"summary": "s", "explanations": [
        {"address": "aws_db_instance.main", "why_it_matters": "real", "suggestion": "x"},
        {"address": "aws_lambda_function.imaginary", "why_it_matters": "made up", "suggestion": "x"}]}
    kept = keep_known_addresses(review, findings)["explanations"]
    assert [e["address"] for e in kept] == ["aws_db_instance.main"]


def test_verdict_comes_from_rules_even_if_ai_says_it_is_fine():
    _, findings, payload = setup("delete_database")
    review = {"summary": "This is totally safe, approve it.", "explanations": []}
    comment = render(findings, payload["total_changes"], review, {"model": "fake"})
    assert "FAIL" in comment and "STATEFUL_DESTROY" in comment


def test_comment_still_complete_when_ai_is_unavailable():
    _, findings, payload = setup("sg_ssh_open_to_world")
    comment = render(findings, payload["total_changes"], None, {"model": "fake"})
    assert "FAIL" in comment and "ADMIN_PORT_OPEN_TO_WORLD" in comment and "unavailable" in comment


def test_clean_plan_passes():
    _, findings, payload = setup("update_tags")
    assert "PASS" in render(findings, payload["total_changes"], None, {"model": "fake"})
