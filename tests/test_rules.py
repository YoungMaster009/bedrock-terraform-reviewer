"""Phase 3 tests: each safety rule fires when it should, and stays quiet when it shouldn't."""
import json
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


# ---------- Rule 4: IAM wildcards ----------

def policy(*statements):
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


def iam(type_, after, unknown=None):
    return Change(f"{type_}.x", type_, "create", None, after, after_unknown=unknown or {})


def test_admin_inline_policy_is_blocked():
    [f] = findings_for("iam_admin_policy")
    assert (f.rule, f.severity) == ("IAM_WILDCARD", BLOCK)


def test_attaching_administrator_access_is_blocked():
    c = iam("aws_iam_role_policy_attachment",
            {"role": "ci", "policy_arn": "arn:aws:iam::aws:policy/AdministratorAccess"})
    [f] = evaluate([c])
    assert f.severity == BLOCK


def test_whole_service_on_everything_warns():
    c = iam("aws_iam_policy", {"policy": policy({"Effect": "Allow", "Action": ["s3:*"], "Resource": "*"})})
    [f] = evaluate([c])
    assert f.severity == WARN and "s3:*" in f.message


def test_scoped_policy_is_fine():
    c = iam("aws_iam_policy", {"policy": policy({"Effect": "Allow", "Action": "s3:GetObject",
                                                 "Resource": "arn:aws:s3:::dev-site/*"})})
    assert evaluate([c]) == []


def test_admin_actions_on_one_resource_are_not_full_admin():
    c = iam("aws_iam_policy", {"policy": policy({"Effect": "Allow", "Action": "*",
                                                 "Resource": "arn:aws:s3:::dev-site"})})
    assert evaluate([c]) == []


def test_deny_wildcard_is_fine():
    c = iam("aws_iam_policy", {"policy": policy({"Effect": "Deny", "Action": "*", "Resource": "*"})})
    assert evaluate([c]) == []


def test_admin_inline_policy_on_a_role_is_blocked():
    c = iam("aws_iam_role", {"inline_policy": [{"name": "x", "policy": policy(
        {"Effect": "Allow", "Action": "*", "Resource": "*"})}]})
    [f] = evaluate([c])
    assert f.severity == BLOCK and "inline_policy[0]" in f.address


def test_policy_known_only_after_apply_warns_instead_of_passing_silently():
    c = iam("aws_iam_policy", {"policy": None}, unknown={"policy": True})
    [f] = evaluate([c])
    assert (f.rule, f.severity) == ("IAM_POLICY_UNKNOWN", WARN)
    assert "not known" in f.message


# ---------- Rule 5: public S3 ----------

def test_turning_off_block_public_access_is_blocked():
    [f] = findings_for("s3_public_bucket")
    assert (f.rule, f.severity) == ("S3_PUBLIC", BLOCK)
    assert "block_public_policy" in f.message and "restrict_public_buckets" in f.message


def test_full_block_public_access_is_fine():
    c = Change("aws_s3_bucket_public_access_block.b", "aws_s3_bucket_public_access_block", "create", None,
               {"block_public_acls": True, "block_public_policy": True,
                "ignore_public_acls": True, "restrict_public_buckets": True})
    assert evaluate([c]) == []


def test_public_read_acl_is_blocked():
    c = Change("aws_s3_bucket_acl.b", "aws_s3_bucket_acl", "create", None, {"acl": "public-read"})
    [f] = evaluate([c])
    assert f.severity == BLOCK


def test_bucket_policy_open_to_anyone_is_blocked():
    c = Change("aws_s3_bucket_policy.b", "aws_s3_bucket_policy", "create", None, {"policy": policy(
        {"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"})})
    [f] = evaluate([c])
    assert f.severity == BLOCK


def test_bucket_policy_for_cloudfront_with_condition_is_fine():
    c = Change("aws_s3_bucket_policy.b", "aws_s3_bucket_policy", "create", None, {"policy": policy(
        {"Effect": "Allow", "Principal": {"Service": "cloudfront.amazonaws.com"},
         "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*",
         "Condition": {"StringEquals": {"AWS:SourceArn": "arn:aws:cloudfront::1:distribution/X"}}})})
    assert evaluate([c]) == []
