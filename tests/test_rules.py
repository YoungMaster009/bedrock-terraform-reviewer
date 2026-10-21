"""Phase 3 tests: each safety rule fires when it should, and stays quiet when it shouldn't."""
from pathlib import Path

import pytest

from plan_parser import Change, load_plan, parse_changes
from rules import BLOCK, WARN, evaluate

FIXTURES = Path(__file__).parent / "fixtures"


def findings_for(name):
    return evaluate(parse_changes(load_plan(FIXTURES / f"{name}.json")))


def sg_create(address, ingress, type_="aws_security_group"):
    return Change(address=address, type=type_, action="create", before=None,
                  after={"ingress": ingress} if type_ == "aws_security_group" else ingress)


# ---------- fixture plans ----------

def test_deleting_a_database_is_blocked():
    [f] = findings_for("delete_database")
    assert (f.rule, f.severity) == ("STATEFUL_DESTROY", BLOCK)


def test_replacing_an_instance_warns_and_names_the_cause():
    [f] = findings_for("replace_instance_ami")
    assert (f.rule, f.severity) == ("REPLACE", WARN)
    assert "ami" in f.message


def test_create_before_destroy_replace_also_warns():
    [f] = findings_for("create_before_destroy")
    assert f.severity == WARN


def test_ssh_open_to_world_is_blocked():
    [f] = findings_for("sg_ssh_open_to_world")
    assert (f.rule, f.severity) == ("ADMIN_PORT_OPEN_TO_WORLD", BLOCK)
    assert "SSH" in f.message


@pytest.mark.parametrize("name", ["update_tags", "noop_and_read"])
def test_safe_plans_have_no_findings(name):
    assert findings_for(name) == []


# ---------- edge cases the rules must get right ----------

def test_replacing_stateful_resource_is_blocked_not_just_warned():
    c = Change("aws_s3_bucket.logs", "aws_s3_bucket", "replace", {}, {}, [["bucket"]])
    [f] = evaluate([c])
    assert f.severity == BLOCK


def test_ssh_from_private_range_is_fine():
    c = sg_create("aws_security_group.a",
                  [{"from_port": 22, "to_port": 22, "protocol": "tcp", "cidr_blocks": ["10.0.0.0/16"]}])
    assert evaluate([c]) == []


def test_https_open_to_world_is_fine():
    c = sg_create("aws_security_group.alb",
                  [{"from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    assert evaluate([c]) == []


def test_port_range_that_includes_ssh_is_blocked():
    c = sg_create("aws_security_group.a",
                  [{"from_port": 0, "to_port": 65535, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    assert {f.message.split()[0] for f in evaluate([c])} == {"SSH", "RDP"}


def test_all_protocols_rule_is_blocked():
    c = sg_create("aws_security_group.a",
                  [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}])
    assert len(evaluate([c])) == 2


def test_ipv6_world_is_blocked():
    c = sg_create("aws_security_group.a",
                  [{"from_port": 22, "to_port": 22, "protocol": "tcp", "ipv6_cidr_blocks": ["::/0"]}])
    [f] = evaluate([c])
    assert "::/0" in f.message


def test_standalone_vpc_ingress_rule_resource_is_checked():
    c = sg_create("aws_vpc_security_group_ingress_rule.rdp",
                  {"from_port": 3389, "to_port": 3389, "ip_protocol": "tcp", "cidr_ipv4": "0.0.0.0/0"},
                  type_="aws_vpc_security_group_ingress_rule")
    [f] = evaluate([c])
    assert "RDP" in f.message


def test_deleting_a_security_group_rule_is_not_an_exposure():
    c = Change("aws_security_group.a", "aws_security_group", "delete",
               {"ingress": [{"from_port": 22, "to_port": 22, "protocol": "tcp",
                             "cidr_blocks": ["0.0.0.0/0"]}]}, None)
    assert evaluate([c]) == []
