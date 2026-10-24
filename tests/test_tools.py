"""Phase 6 tests: tools are read-only and safe, and the agent loop always ends."""
import json
from pathlib import Path

import review
from plan_parser import load_plan, parse_changes
from review import ask_model, build_input, keep_known_addresses
from rules import evaluate
from tools import MAX_CALLS, ToolBox

FIXTURES = Path(__file__).parent / "fixtures"


def setup(name):
    changes = parse_changes(load_plan(FIXTURES / f"{name}.json"))
    findings = evaluate(changes)
    return changes, findings, build_input(changes, findings, [])


def tool_turn(*calls):
    """A model turn that asks for tools: calls are (id, name, input)."""
    return {"stopReason": "tool_use", "usage": {"inputTokens": 10, "outputTokens": 5},
            "output": {"message": {"role": "assistant", "content":
                       [{"toolUse": {"toolUseId": i, "name": n, "input": a}} for i, n, a in calls]}}}


def final_turn(obj, prefix=""):
    return {"stopReason": "end_turn", "usage": {"inputTokens": 20, "outputTokens": 30},
            "output": {"message": {"role": "assistant", "content": [{"text": prefix + json.dumps(obj)}]}}}


class ScriptedClient:
    def __init__(self, *turns):
        self.turns, self.requests = list(turns), []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        return self.turns.pop(0)


GOOD = {"summary": "Deletes the database.", "explanations": [
    {"address": "aws_db_instance.main", "why_it_matters": "Data loss.", "suggestion": "Snapshot first.",
     "standard": "STD-DATA-01"}]}


# ---------- the tools ----------

def test_get_change_returns_names_and_replace_cause():
    changes, _, _ = setup("replace_instance_ami")
    result, ok = ToolBox(changes).run("get_change", {"address": "module.compute.aws_instance.web"})
    assert ok and result["action"] == "replace" and result["replace_forced_by"] == ["ami"]
    assert "ami-0bbb2222" not in json.dumps(result)          # values never leave the plan


def test_unknown_address_is_an_error_not_a_crash():
    changes, _, _ = setup("delete_database")
    result, ok = ToolBox(changes).run("get_change", {"address": "aws_lambda_function.imaginary"})
    assert not ok and "error" in result


def test_lookup_standard_records_what_was_read():
    changes, _, _ = setup("delete_database")
    box = ToolBox(changes)
    result, ok = box.run("lookup_standard", {"id": "std-data-01"})
    assert ok and result["fix"] and box.looked_up == {"STD-DATA-01"}


def test_unknown_tool_and_bad_input_are_handled():
    changes, _, _ = setup("delete_database")
    box = ToolBox(changes)
    assert box.run("delete_everything", {})[1] is False
    assert box.run("get_change", "not a dict")[1] is False


def test_tool_budget_is_enforced():
    changes, _, _ = setup("delete_database")
    box = ToolBox(changes)
    for _ in range(MAX_CALLS):
        box.run("lookup_standard", {"id": "STD-DATA-01"})
    result, ok = box.run("lookup_standard", {"id": "STD-DATA-01"})
    assert not ok and "budget" in result["error"]


# ---------- the agent loop ----------

def test_payload_is_an_outline_without_details():
    _, _, payload = setup("replace_instance_ami")
    assert "replace_forced_by" not in json.dumps(payload)    # details come from get_change


def test_loop_runs_tools_then_answers():
    changes, findings, payload = setup("delete_database")
    client = ScriptedClient(
        tool_turn(("t1", "get_change", {"address": "aws_db_instance.main"}),
                  ("t2", "lookup_standard", {"id": "STD-DATA-01"})),
        final_turn(GOOD))
    box = ToolBox(changes)
    review_, metrics = ask_model(payload, client, box)
    assert review_["summary"] == "Deletes the database."
    assert metrics["tool_calls"] == 2 and metrics["input_tokens"] == 30
    second_request = client.requests[1]["messages"]
    assert second_request[-1]["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert "toolConfig" in client.requests[0]


def test_loop_always_ends_even_if_the_model_never_stops():
    changes, _, payload = setup("delete_database")
    turns = [tool_turn((f"t{i}", "lookup_standard", {"id": "STD-DATA-01"})) for i in range(review.MAX_ROUNDS)]
    review_, metrics = ask_model(payload, ScriptedClient(*turns), ToolBox(changes))
    assert review_ is None and "rounds" in metrics["error"]


def test_thinking_tags_and_extra_words_are_tolerated():
    changes, _, payload = setup("delete_database")
    client = ScriptedClient(final_turn(GOOD, prefix="<thinking>let me check</thinking> Here you go: "))
    review_, _ = ask_model(payload, client, ToolBox(changes))
    assert review_["explanations"][0]["standard"] == "STD-DATA-01"


def test_a_standard_the_model_looked_up_may_be_cited():
    _, findings, _ = setup("delete_database")
    review_ = json.loads(json.dumps(GOOD))
    kept = keep_known_addresses(review_, findings, standards=[], looked_up={"STD-DATA-01"})
    assert kept["explanations"][0]["standard"] == "STD-DATA-01"
