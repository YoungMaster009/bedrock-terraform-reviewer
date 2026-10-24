"""Project 3, Phase 7: prove the reviewer role is least privilege, on every pull request.

Runs in CI as github-actions-plan-reviewer. Calls that must be denied have to fail with
AccessDeniedException specifically; any other outcome means IAM let the call through.
Don't run this with admin credentials: an admin is allowed everything, so the checks would fail.
"""
import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-1"

MUST_DENY = [
    ("Nova Pro through the US profile (unapproved model)", "converse", "us.amazon.nova-pro-v1:0"),
    ("Cohere Embed through the GLOBAL profile (unapproved route)", "embed", "global.cohere.embed-v4:0"),
    ("Nova Lite called directly, no profile (condition key)", "converse", "amazon.nova-lite-v1:0"),
]
MUST_ALLOW = [
    ("Nova Lite through the US profile (positive control)", "converse", "us.amazon.nova-lite-v1:0"),
]


def call(client, kind: str, model_id: str) -> None:
    if kind == "converse":
        client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
                        inferenceConfig={"maxTokens": 5})
    else:
        client.invoke_model(modelId=model_id, body=json.dumps(
            {"texts": ["test"], "input_type": "search_query", "embedding_types": ["float"]}))


def outcome(client, kind: str, model_id: str) -> str:
    try:
        call(client, kind, model_id)
        return "allowed"
    except ClientError as err:
        return err.response["Error"]["Code"]


def check(client) -> list[tuple[str, str, str, bool]]:
    rows = []
    for label, kind, model in MUST_DENY:
        got = outcome(client, kind, model)
        rows.append((label, "AccessDeniedException", got, got == "AccessDeniedException"))
    for label, kind, model in MUST_ALLOW:
        got = outcome(client, kind, model)
        rows.append((label, "allowed", got, got == "allowed"))
    return rows


def main() -> None:
    rows = check(boto3.client("bedrock-runtime", region_name=REGION))
    for label, expected, got, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {label}\n      expected {expected}, got {got}")
    passed = all(ok for *_, ok in rows)
    print(f"\nLeast privilege {'proven' if passed else 'NOT proven'}: {sum(r[3] for r in rows)}/{len(rows)} checks")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
