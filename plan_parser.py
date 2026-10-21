"""Project 3, Phase 2: read `terraform show -json` output and list every resource change."""
import json
import sys
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Change:
    address: str            # e.g. module.network.aws_vpc.this
    type: str               # e.g. aws_vpc
    action: str             # create, update, delete, replace, read, no-op
    before: dict | None     # attributes before the change (None for create)
    after: dict | None      # attributes after the change (None for delete)
    replace_paths: list = field(default_factory=list)  # which attributes force a replace


def classify(actions: list[str]) -> str:
    """Turn Terraform's action list into one word."""
    if actions in (["delete", "create"], ["create", "delete"]):
        return "replace"
    if len(actions) == 1:
        return actions[0]
    return "+".join(actions)  # unexpected combination: keep it visible, don't hide it


def load_plan(path: str) -> dict:
    # utf-8-sig also handles a file saved with a byte-order mark
    with open(path, encoding="utf-8-sig") as f:
        plan = json.load(f)
    if "resource_changes" not in plan:
        raise SystemExit(f"{path} has no resource_changes. Is it `terraform show -json` output?")
    return plan


def parse_changes(plan: dict) -> list[Change]:
    changes = []
    for rc in plan["resource_changes"]:
        change = rc["change"]
        changes.append(Change(
            address=rc["address"],
            type=rc["type"],
            action=classify(change["actions"]),
            before=change.get("before"),
            after=change.get("after"),
            replace_paths=change.get("replace_paths", []),
        ))
    return changes


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python plan_parser.py <plan.json>")

    changes = parse_changes(load_plan(sys.argv[1]))
    real = [c for c in changes if c.action not in ("no-op", "read")]

    for c in real:
        line = f"{c.action:<8} {c.address}"
        if c.replace_paths:
            line += f"   (forced by: {c.replace_paths})"
        print(line)

    counts = Counter(c.action for c in changes)
    print(f"\n{len(real)} changes: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))


if __name__ == "__main__":
    main()
