"""Project 3, Phase 3: deterministic safety rules.

These rules decide pass or fail. The LLM (Phase 4) only explains the findings;
it never makes the safety decision.
"""
import json
import sys
from dataclasses import dataclass

from plan_parser import Change, load_plan, parse_changes

BLOCK = "BLOCK"   # fails the check: a human must fix or explicitly override
WARN = "WARN"     # passes, but the reviewer calls it out

# Resources that hold data. Deleting or replacing one can lose that data.
STATEFUL_TYPES = {
    "aws_db_instance", "aws_rds_cluster", "aws_dynamodb_table", "aws_s3_bucket",
    "aws_efs_file_system", "aws_ebs_volume", "aws_elasticache_replication_group",
    "aws_kms_key", "aws_secretsmanager_secret",
}

ADMIN_PORTS = {22: "SSH", 3389: "RDP"}
WORLD = {"0.0.0.0/0", "::/0"}


@dataclass
class Finding:
    rule: str
    severity: str
    address: str
    message: str


# ---------- Rule 1 and 2: destroying things ----------

def check_destroys(c: Change) -> list[Finding]:
    if c.action not in ("delete", "replace"):
        return []
    verb = "deleted" if c.action == "delete" else "replaced (destroyed, then recreated)"
    if c.type in STATEFUL_TYPES:
        return [Finding("STATEFUL_DESTROY", BLOCK, c.address,
                        f"{c.type} will be {verb}. Its data may be lost.")]
    if c.action == "replace":
        cause = ", ".join(".".join(map(str, p)) for p in c.replace_paths) or "unknown attribute"
        return [Finding("REPLACE", WARN, c.address,
                        f"{c.type} will be replaced because {cause} changed. Check whether that causes downtime.")]
    return []


# ---------- Rule 3: admin ports open to the internet ----------

def _ingress_rules(c: Change) -> list[dict]:
    """Normalize the three ways Terraform can express an ingress rule."""
    a = c.after or {}
    if c.type == "aws_security_group":
        return [r for r in (a.get("ingress") or []) if r]
    if c.type == "aws_security_group_rule" and a.get("type") == "ingress":
        return [a]
    if c.type == "aws_vpc_security_group_ingress_rule":
        return [{
            "from_port": a.get("from_port"), "to_port": a.get("to_port"),
            "protocol": a.get("ip_protocol"),
            "cidr_blocks": [a["cidr_ipv4"]] if a.get("cidr_ipv4") else [],
            "ipv6_cidr_blocks": [a["cidr_ipv6"]] if a.get("cidr_ipv6") else [],
        }]
    return []


def _covers(rule: dict, port: int) -> bool:
    protocol = str(rule.get("protocol", "")).lower()
    if protocol in ("-1", "all"):
        return True                      # all protocols, all ports
    if protocol not in ("tcp", "6"):
        return False
    lo, hi = rule.get("from_port"), rule.get("to_port")
    return lo is not None and hi is not None and lo <= port <= hi


def check_admin_ports(c: Change) -> list[Finding]:
    if c.action not in ("create", "update", "replace"):
        return []
    findings = []
    for rule in _ingress_rules(c):
        sources = set(rule.get("cidr_blocks") or []) | set(rule.get("ipv6_cidr_blocks") or [])
        open_to = sorted(sources & WORLD)
        if not open_to:
            continue
        for port, name in ADMIN_PORTS.items():
            if _covers(rule, port):
                findings.append(Finding("ADMIN_PORT_OPEN_TO_WORLD", BLOCK, c.address,
                                        f"{name} (port {port}) is open to {', '.join(open_to)}."))
    return findings


# ---------- Rule 4: IAM wildcards ----------

POLICY_TYPES = {"aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"}
ATTACHMENT_TYPES = {"aws_iam_role_policy_attachment", "aws_iam_user_policy_attachment",
                    "aws_iam_group_policy_attachment", "aws_iam_policy_attachment"}
ADMIN_POLICY_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _statements(policy_json: str) -> list[dict]:
    doc = json.loads(policy_json)
    return [s for s in _as_list(doc.get("Statement")) if isinstance(s, dict)]


def _wildcard_findings(address: str, policy_json: str) -> list[Finding]:
    findings = []
    for s in _statements(policy_json):
        if s.get("Effect") != "Allow":
            continue
        actions = _as_list(s.get("Action"))
        if "*" not in _as_list(s.get("Resource")):
            continue
        if "*" in actions or "*:*" in actions:
            findings.append(Finding("IAM_WILDCARD", BLOCK, address,
                                    'Allows every action ("*") on every resource ("*"): full admin.'))
        else:
            broad = sorted(a for a in actions if isinstance(a, str) and a.endswith(":*"))
            if broad:
                findings.append(Finding("IAM_WILDCARD", WARN, address,
                                        f"Allows all of {', '.join(broad)} on every resource. Scope it down."))
    return findings


def check_iam(c: Change) -> list[Finding]:
    if c.action not in ("create", "update", "replace"):
        return []
    a = c.after or {}

    if c.type in ATTACHMENT_TYPES and a.get("policy_arn") == ADMIN_POLICY_ARN:
        return [Finding("IAM_WILDCARD", BLOCK, c.address, "Attaches the AdministratorAccess managed policy.")]

    policies = []                                   # (label, json string or None)
    if c.type in POLICY_TYPES:
        policies.append((c.address, a.get("policy")))
    if c.type == "aws_iam_role":
        for i, inline in enumerate(a.get("inline_policy") or []):
            policies.append((f"{c.address} inline_policy[{i}]", inline.get("policy")))

    findings = []
    for label, policy in policies:
        if policy:
            findings += _wildcard_findings(label, policy)
        elif c.type in POLICY_TYPES and c.after_unknown.get("policy"):
            findings.append(Finding("IAM_POLICY_UNKNOWN", WARN, label,
                                    "Policy is not known until apply, so it could not be checked."))
    return findings


# ---------- Rule 5: public S3 ----------

PUBLIC_ACLS = {"public-read", "public-read-write", "authenticated-read"}
BLOCK_SETTINGS = ["block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"]


def check_s3_public(c: Change) -> list[Finding]:
    if c.action not in ("create", "update", "replace"):
        return []
    a = c.after or {}

    if c.type == "aws_s3_bucket_public_access_block":
        off = [s for s in BLOCK_SETTINGS if a.get(s) is False]
        if off:
            return [Finding("S3_PUBLIC", BLOCK, c.address,
                            f"Turns off Block Public Access: {', '.join(off)}.")]

    if c.type in ("aws_s3_bucket_acl", "aws_s3_bucket") and a.get("acl") in PUBLIC_ACLS:
        return [Finding("S3_PUBLIC", BLOCK, c.address, f'Uses the public ACL "{a["acl"]}".')]

    if c.type == "aws_s3_bucket_policy" and a.get("policy"):
        for s in _statements(a["policy"]):
            principal = s.get("Principal")
            anyone = principal == "*" or (isinstance(principal, dict) and "*" in _as_list(principal.get("AWS")))
            if s.get("Effect") == "Allow" and anyone and not s.get("Condition"):
                return [Finding("S3_PUBLIC", BLOCK, c.address,
                                'Bucket policy allows anyone ("Principal": "*") with no condition.')]
    return []


RULES = [check_destroys, check_admin_ports, check_iam, check_s3_public]


def evaluate(changes: list[Change]) -> list[Finding]:
    return [f for c in changes for rule in RULES for f in rule(c)]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python rules.py <plan.json>")
    findings = evaluate(parse_changes(load_plan(sys.argv[1])))
    for f in findings:
        print(f"{f.severity:<5} {f.rule:<25} {f.address}\n      {f.message}")
    blocked = any(f.severity == BLOCK for f in findings)
    print(f"\n{len(findings)} findings. Verdict: {'FAIL' if blocked else 'PASS'}")
    sys.exit(1 if blocked else 0)   # a non-zero exit code fails the CI check


if __name__ == "__main__":
    main()
