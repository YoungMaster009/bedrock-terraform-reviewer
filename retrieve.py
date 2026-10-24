"""Project 3, Phase 5: retrieve team standards for a plan (hybrid RAG).

1. Direct mapping: every rule ID maps to the standard it enforces (deterministic).
2. Semantic search: embeddings find other standards relevant to the changes.
3. Fallback: if embeddings are unavailable, a keyword match keeps retrieval working.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent
STANDARDS_PATH = ROOT / "standards.md"
INDEX_PATH = ROOT / "standards_index.json"
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "us.cohere.embed-v4:0")
REGION = os.environ.get("AWS_REGION", "us-west-1")

RULE_TO_STANDARD = {
    "STATEFUL_DESTROY": "STD-DATA-01",
    "REPLACE": "STD-CHG-01",
    "ADMIN_PORT_OPEN_TO_WORLD": "STD-NET-01",
    "IAM_WILDCARD": "STD-IAM-01",
    "IAM_POLICY_UNKNOWN": "STD-IAM-04",
    "S3_PUBLIC": "STD-DATA-02",
}
MIN_SCORE = {"embedding": 0.30, "keyword": 0.15}   # below this, a match is too weak to show
TOP_K = 2


@dataclass
class Standard:
    id: str
    title: str
    text: str            # the full section: rule, why, fix

    def field(self, name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+)$", self.text, re.MULTILINE)
        return m.group(1).strip() if m else ""


def load_standards(path: Path = STANDARDS_PATH) -> list[Standard]:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    standards = []
    for s in sections:
        header, _, body = s.partition("\n")
        sid, _, title = header.partition(":")
        standards.append(Standard(sid.strip(), title.strip(), body.strip()))
    return standards


def content_hash(path: Path = STANDARDS_PATH) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---------- embeddings ----------

class BedrockEmbedder:
    def __init__(self, client=None):
        self.client = client or __import__("boto3").client("bedrock-runtime", region_name=REGION)

    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        resp = self.client.invoke_model(
            modelId=EMBED_MODEL_ID,
            body=json.dumps({"texts": texts, "input_type": input_type, "embedding_types": ["float"]}),
        )
        vectors = json.loads(resp["body"].read())["embeddings"]
        return vectors["float"] if isinstance(vectors, dict) else vectors


def cosine(a, b) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def build_index(embedder, standards: list[Standard]) -> dict:
    vectors = embedder.embed([f"{s.title}. {s.text}" for s in standards], "search_document")
    return {"model": EMBED_MODEL_ID, "standards_sha256": content_hash(),
            "vectors": {s.id: [round(v, 6) for v in vec] for s, vec in zip(standards, vectors)}}


def load_index() -> dict | None:
    if not INDEX_PATH.exists():
        return None
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    fresh = index.get("standards_sha256") == content_hash() and index.get("model") == EMBED_MODEL_ID
    return index if fresh else None        # stale index: standards or model changed


# ---------- keyword fallback ----------

STOP = set("a an and are as at be by for from in is it its of on or that the this to with will "
           "aws terraform plan changes create update delete replace".split())   # words every plan shares


def _terms(text: str) -> dict:
    counts = {}
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("_", " ")):
        if w not in STOP and len(w) > 1:
            counts[w] = counts.get(w, 0) + 1
    return counts


def keyword_score(query: str, doc: str) -> float:
    q, d = _terms(query), _terms(doc)
    common = set(q) & set(d)
    num = sum(q[t] * d[t] for t in common)
    den = math.sqrt(sum(v * v for v in q.values())) * math.sqrt(sum(v * v for v in d.values()))
    return num / den if den else 0.0


# ---------- retrieval ----------

def describe_changes(changes) -> str:
    pairs = sorted({(c.action, c.type) for c in changes if c.action not in ("no-op", "read")})
    return "Terraform plan changes: " + ", ".join(f"{a} {t.replace('_', ' ')}" for a, t in pairs[:40])


def retrieve(changes, findings, embedder=None) -> tuple[list[dict], dict]:
    """Returns (standards to give the model, retrieval metrics)."""
    standards = {s.id: s for s in load_standards()}
    mapped = []
    for f in findings:
        sid = RULE_TO_STANDARD.get(f.rule)
        if sid and sid not in mapped:
            mapped.append(sid)

    query = describe_changes(changes)
    candidates = [s for sid, s in standards.items() if sid not in mapped]
    mode, scored = "keyword", []
    try:
        index = load_index()
        if embedder is None:
            embedder = BedrockEmbedder()
        if index is None:                                   # missing or stale: rebuild in memory
            index = build_index(embedder, list(standards.values()))
        [q_vec] = embedder.embed([query], "search_query")
        scored = [(cosine(q_vec, index["vectors"][s.id]), s) for s in candidates]
        mode = "embedding"
    except Exception as err:                                # quota, permissions, outage: degrade
        print(f"warning: embeddings unavailable ({type(err).__name__}); using keyword match", file=sys.stderr)
        scored = [(keyword_score(query, f"{s.title} {s.text}"), s) for s in candidates]

    related = [s.id for score, s in sorted(scored, key=lambda x: x[0], reverse=True)
               if score >= MIN_SCORE[mode]][:TOP_K]

    def pack(sid, why):
        s = standards[sid]
        return {"id": s.id, "title": s.title, "rule": s.field("Rule"), "fix": s.field("Fix"), "matched_by": why}

    result = [pack(sid, "rule") for sid in mapped] + [pack(sid, mode) for sid in related]
    return result, {"retrieval": mode, "standards_cited": len(result)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the standards embedding index.")
    ap.add_argument("--build", action="store_true", help="embed standards.md and write standards_index.json")
    args = ap.parse_args()
    if not args.build:
        raise SystemExit("usage: python retrieve.py --build")
    standards = load_standards()
    index = build_index(BedrockEmbedder(), standards)
    INDEX_PATH.write_text(json.dumps(index), encoding="utf-8", newline="\n")
    print(f"indexed {len(standards)} standards with {EMBED_MODEL_ID} (1 request) -> {INDEX_PATH.name}")


if __name__ == "__main__":
    main()
