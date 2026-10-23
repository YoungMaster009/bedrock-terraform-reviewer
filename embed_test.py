"""Project 3, Phase 5: first embedding call, plus a tiny demo of how retrieval works.

Titan Text Embeddings V2 has an on-demand quota of 0 in this account (not adjustable),
so this uses Cohere Embed v4 through the US cross-Region inference profile (quota: 20/min).
"""
import json
import math
import os
import time

import boto3

REGION = "us-west-1"
MODEL_ID = os.environ.get("EMBED_MODEL_ID", "us.cohere.embed-v4:0")

client = boto3.client("bedrock-runtime", region_name=REGION)


def embed(texts: list[str], input_type: str) -> list[list[float]]:
    """One request for many texts: Cohere accepts a batch, which saves quota."""
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"texts": texts, "input_type": input_type, "embedding_types": ["float"]}),
    )
    body = json.loads(resp["body"].read())
    vectors = body["embeddings"]
    return vectors["float"] if isinstance(vectors, dict) else vectors


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


query = "Security group allows port 22 from 0.0.0.0/0"
candidates = {
    "STD-NET-01": "No admin ports open to the internet. Security groups must never allow SSH or RDP from anywhere.",
    "STD-TAG-01": "Tag every resource with Project, Environment, and ManagedBy tags.",
    "STD-DATA-02": "S3 buckets stay private. Block Public Access stays on.",
}

start = time.perf_counter()
docs = embed(list(candidates.values()), "search_document")   # request 1: all standards at once
[q_vec] = embed([query], "search_query")                     # request 2: the query
print(f"model: {MODEL_ID} in {REGION}")
print(f"vector length: {len(q_vec)}, 2 requests, latency: {(time.perf_counter() - start) * 1000:.0f} ms")
print(f'\nquery: "{query}"\n')

scores = {sid: cosine(q_vec, vec) for sid, vec in zip(candidates, docs)}
for sid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
    print(f"  {score:.3f}  {sid}")
