"""Phase 2 tests: the parser must classify every kind of change correctly."""
import json
from pathlib import Path

import pytest

from plan_parser import classify, load_plan, parse_changes

FIXTURES = Path(__file__).parent / "fixtures"


def changes_for(name):
    return parse_changes(load_plan(FIXTURES / f"{name}.json"))


@pytest.mark.parametrize("actions, expected", [
    (["create"], "create"),
    (["update"], "update"),
    (["delete"], "delete"),
    (["delete", "create"], "replace"),   # default replace: destroy first
    (["create", "delete"], "replace"),   # create_before_destroy
    (["no-op"], "no-op"),
    (["read"], "read"),
])
def test_classify(actions, expected):
    assert classify(actions) == expected


def test_unknown_action_combination_stays_visible():
    assert classify(["update", "delete"]) == "update+delete"


def test_update_tags():
    [c] = changes_for("update_tags")
    assert c.action == "update"
    assert c.before["tags"] != c.after["tags"]


def test_replace_records_what_forced_it():
    [c] = changes_for("replace_instance_ami")
    assert c.action == "replace"
    assert c.address == "module.compute.aws_instance.web"
    assert c.replace_paths == [["ami"]]


def test_create_before_destroy_is_still_a_replace():
    [c] = changes_for("create_before_destroy")
    assert c.action == "replace"


def test_delete_has_no_after():
    [c] = changes_for("delete_database")
    assert c.action == "delete"
    assert c.type == "aws_db_instance"
    assert c.after is None


def test_new_security_group_keeps_its_rules():
    [c] = changes_for("sg_ssh_open_to_world")
    assert c.action == "create"
    assert c.after["ingress"][0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_noop_and_read_are_parsed_but_distinguishable():
    actions = sorted(c.action for c in changes_for("noop_and_read"))
    assert actions == ["no-op", "read", "update"]


def test_file_with_byte_order_mark(tmp_path):
    plan = {"resource_changes": []}
    path = tmp_path / "bom.json"
    path.write_text(json.dumps(plan), encoding="utf-8-sig")
    assert load_plan(path) == plan


def test_rejects_files_that_are_not_plans(tmp_path):
    path = tmp_path / "not_a_plan.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        load_plan(path)
