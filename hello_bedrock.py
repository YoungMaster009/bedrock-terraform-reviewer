"""Project 3, Phase 1: first call to Amazon Bedrock (Nova Lite via the US inference profile)."""
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-1"
MODEL_ID = "us.amazon.nova-lite-v1:0"  # cross-Region inference profile, not the plain model ID

client = boto3.client("bedrock-runtime", region_name=REGION)

prompt = "In one sentence, why should a Terraform plan be reviewed before apply?"

start = time.perf_counter()
try:
    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0.2},
    )
except ClientError as err:
    code = err.response["Error"]["Code"]
    print(f"Bedrock call failed: {code}")
    print(err.response["Error"]["Message"])
    raise SystemExit(1)
latency_ms = (time.perf_counter() - start) * 1000

answer = response["output"]["message"]["content"][0]["text"]
usage = response["usage"]

print(f"model: {MODEL_ID} in {REGION}")
print(f"answer: {answer}")
print(f"tokens in: {usage['inputTokens']}, out: {usage['outputTokens']}, latency: {latency_ms:.0f} ms")
