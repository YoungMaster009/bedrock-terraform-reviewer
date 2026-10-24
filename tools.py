"""Project 3, Phase 6: read-only tools the model can call while writing a review.

Instead of receiving every detail up front, the model asks for what it needs.
Every tool is read-only, runs locally in Python, and never touches AWS.
"""
import json

from plan_parser import Change
from retrieve import load_standards

MAX_CALLS = 6   # hard budget per review: an agent loop must always end


class ToolBox:
    def __init__(self, changes: list[Change]):
        self.changes = {c.address: c for c in changes if c.action not in ("no-op", "read")}
        self.standards = {s.id: s for s in load_standards()}
        self.calls = 0
        self.looked_up = set()          # standards the model actually read (allowed to be cited)

    def specs(self) -> list[dict]:
        return [
            {"toolSpec": {
                "name": "get_change",
                "description": "Details of one planned resource change: action, which attributes change "
                               "(names only, never values), and what forced a replacement.",
                "inputSchema": {"json": {"type": "object", "required": ["address"],
                                         "properties": {"address": {"type": "string"}}}}}},
            {"toolSpec": {
                "name": "lookup_standard",
                "description": "Full text of one team standard (rule, why, fix) by its id, e.g. STD-NET-01.",
                "inputSchema": {"json": {"type": "object", "required": ["id"],
                                         "properties": {"id": {"type": "string"}}}}}},
        ]

    def run(self, name: str, args: dict) -> tuple[dict, bool]:
        """Returns (result, ok). Bad input gets an error result, never an exception."""
        self.calls += 1
        if self.calls > MAX_CALLS:
            return {"error": "Tool budget used up. Write your final answer now."}, False
        args = args if isinstance(args, dict) else {}
        if name == "get_change":
            return self._get_change(str(args.get("address", "")))
        if name == "lookup_standard":
            return self._lookup_standard(str(args.get("id", "")))
        return {"error": f"Unknown tool: {name}"}, False

    def _get_change(self, address: str) -> tuple[dict, bool]:
        c = self.changes.get(address)
        if not c:
            return {"error": f"No change with address {address!r} in this plan."}, False
        result = {"address": c.address, "type": c.type, "action": c.action}
        if c.action in ("update", "replace") and c.before and c.after:
            result["changed_attributes"] = sorted(k for k in c.after if c.before.get(k) != c.after.get(k))
        if c.replace_paths:
            result["replace_forced_by"] = [".".join(map(str, p)) for p in c.replace_paths]
        return result, True

    def _lookup_standard(self, sid: str) -> tuple[dict, bool]:
        s = self.standards.get(sid.strip().upper())
        if not s:
            return {"error": f"No standard with id {sid!r}."}, False
        self.looked_up.add(s.id)
        return {"id": s.id, "title": s.title, "rule": s.field("Rule"),
                "why": s.field("Why"), "fix": s.field("Fix")}, True


def tool_result_block(tool_use_id: str, result: dict, ok: bool) -> dict:
    # No "status" field: Bedrock only accepts it for some model families. Errors travel in the JSON instead.
    return {"toolResult": {"toolUseId": tool_use_id, "content": [{"text": json.dumps(result)}]}}
