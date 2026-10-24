"""Phase 5 tests: hybrid retrieval maps rules to standards, ranks the rest, and degrades gracefully."""
import json
import re
from pathlib import Path

import retrieve
from plan_parser import Change, load_plan, parse_changes
from retrieve import RULE_TO_STANDARD, keyword_score, load_standards
from review import build_input, keep_known_addresses, render
from rules import evaluate

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEmbedder:
    """Deterministic vectors from keywords, so tests need no AWS: dimension i = 'mentions topic i'."""
    TOPICS = ["ssh", "bucket", "tag", "iam", "delete", "encrypt"]

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def embed(self, texts, input_type):
        self.calls += 1
        if self.fail:
            raise RuntimeError("ThrottlingException")
        return [[1.0 if t in text.lower() else 0.01 for t in self.TOPICS] for text in texts]


def setup(name):
    changes = parse_changes(load_plan(FIXTURES / f"{name}.json"))
    return changes, evaluate(changes)


def test_standards_file_parses_with_rule_and_fix():
    standards = load_standards()
    assert len(standards) == 14
    assert all(s.field("Rule") and s.field("Fix") for s in standards)


def test_every_rule_maps_to_a_real_standard():
    rule_ids = set(re.findall(r'Finding\("([A-Z_]+)"', Path(retrieve.__file__).with_name("rules.py").read_text()))
    ids = {s.id for s in load_standards()}
    assert rule_ids <= set(RULE_TO_STANDARD), f"unmapped rules: {rule_ids - set(RULE_TO_STANDARD)}"
    assert set(RULE_TO_STANDARD.values()) <= ids


def test_finding_maps_directly_to_its_standard(monkeypatch):
    monkeypatch.setattr(retrieve, "load_index", lambda: None)
    changes, findings = setup("sg_ssh_open_to_world")
    standards, metrics = retrieve.retrieve(changes, findings, FakeEmbedder())
    assert standards[0]["id"] == "STD-NET-01" and standards[0]["matched_by"] == "rule"
    assert metrics["retrieval"] == "embedding"


def test_semantic_search_never_repeats_a_mapped_standard(monkeypatch):
    monkeypatch.setattr(retrieve, "load_index", lambda: None)
    changes, findings = setup("sg_ssh_open_to_world")
    standards, _ = retrieve.retrieve(changes, findings, FakeEmbedder())
    ids = [s["id"] for s in standards]
    assert len(ids) == len(set(ids))


def test_embedding_failure_falls_back_to_keywords(monkeypatch):
    monkeypatch.setattr(retrieve, "load_index", lambda: None)
    changes, findings = setup("delete_database")
    standards, metrics = retrieve.retrieve(changes, findings, FakeEmbedder(fail=True))
    assert metrics["retrieval"] == "keyword"
    assert standards[0]["id"] == "STD-DATA-01"      # the rule mapping still works offline


def test_keyword_score_prefers_the_relevant_standard():
    q = "create aws security group ssh port 22"
    assert keyword_score(q, "No SSH or RDP open in security groups") > keyword_score(q, "Tag every resource")


def test_stale_index_is_ignored(tmp_path, monkeypatch):
    index = tmp_path / "standards_index.json"
    index.write_text(json.dumps({"model": retrieve.EMBED_MODEL_ID, "standards_sha256": "old", "vectors": {}}))
    monkeypatch.setattr(retrieve, "INDEX_PATH", index)
    assert retrieve.load_index() is None


def test_model_sees_standards_in_its_input():
    changes, findings = setup("delete_database")
    standards = [{"id": "STD-DATA-01", "title": "t", "rule": "r", "fix": "f", "matched_by": "rule"}]
    assert build_input(changes, findings, standards)["standards"][0]["id"] == "STD-DATA-01"


def test_invented_standard_citations_are_dropped():
    _, findings = setup("delete_database")
    standards = [{"id": "STD-DATA-01", "title": "t", "rule": "r", "fix": "f", "matched_by": "rule"}]
    review = {"summary": "s", "explanations": [
        {"address": "aws_db_instance.main", "why_it_matters": "w", "suggestion": "x", "standard": "STD-MADE-UP"}]}
    [e] = keep_known_addresses(review, findings, standards)["explanations"]
    assert "standard" not in e


def test_comment_cites_standard_and_lists_related_ones():
    _, findings = setup("delete_database")
    standards = [{"id": "STD-DATA-01", "title": "Protect stateful resources", "rule": "r", "fix": "f",
                  "matched_by": "rule"},
                 {"id": "STD-TAG-01", "title": "Tag every resource", "rule": "Tag it.", "fix": "f",
                  "matched_by": "embedding"}]
    review = {"summary": "s", "explanations": [
        {"address": "aws_db_instance.main", "why_it_matters": "w", "suggestion": "x", "standard": "STD-DATA-01"}]}
    comment = render(findings, 1, review, {"model": "fake"}, standards)
    assert "See **STD-DATA-01**" in comment
    assert "Related team standards" in comment and "STD-TAG-01" in comment


def test_findings_table_cites_the_standard_even_without_ai():
    _, findings = setup("sg_ssh_open_to_world")
    comment = render(findings, 1, None, {"model": "fake"}, [])
    assert "| STD-NET-01 |" in comment
