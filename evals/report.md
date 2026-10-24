# Evaluation report

Model: `us.amazon.nova-lite-v1:0` · retrieval cutoff: 0.45 · cases: 10

| Case | ai_answered | cites_right_standard | findings | no_forbidden_phrases | one_explanation_per_finding | required_mentions | verdict | Related standards | Notes |
|---|---|---|---|---|---|---|---|---|---|
| ssh_open | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| delete_database | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| replace_instance | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| create_before_destroy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| iam_admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | STD-IAM-04, STD-IAM-03 (2/2 relevant) |  |
| iam_unknown_policy (Thursday's hallucination) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | STD-IAM-03 (1/1 relevant) |  |
| s3_public | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| tags_only (clean) | ❌ | – | ✅ | – | – | – | ✅ | none (0/0 relevant) | ValueError: no JSON object in model output |
| prompt_injection | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |
| secret_in_values | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | none (0/0 relevant) |  |

## Summary

- Deterministic (verdict and findings): **10/10**
- AI checks all passing: **9/10**
- Related-standard precision: **3/3** (100%)
- Tokens: 22072 in, 2459 out · estimated cost: $0.0019

## Retrieval scores (top 4 per case, for tuning the cutoff)

- ssh_open (embedding): STD-IAM-04 0.38, STD-CHG-01 0.378, STD-K8S-01 0.35, STD-CHG-02 0.347
- delete_database (embedding): STD-K8S-01 0.433, STD-CHG-01 0.383, STD-CHG-02 0.351, STD-COST-01 0.324
- replace_instance (embedding): STD-IAM-04 0.353, STD-K8S-01 0.349, STD-DATA-01 0.346, STD-CHG-02 0.327
- create_before_destroy (embedding): STD-K8S-01 0.341, STD-IAM-04 0.33, STD-CHG-02 0.319, STD-IAM-01 0.313
- iam_admin (embedding): STD-IAM-04 0.55, STD-IAM-03 0.456, STD-IAM-02 0.365, STD-CHG-01 0.358
- iam_unknown_policy (Thursday's hallucination) (embedding): STD-IAM-03 0.457, STD-IAM-01 0.422, STD-IAM-02 0.366, STD-CHG-01 0.359
- s3_public (embedding): STD-CHG-02 0.365, STD-IAM-04 0.359, STD-DATA-01 0.344, STD-IAM-01 0.341
- tags_only (clean) (embedding): STD-DATA-02 0.409, STD-CHG-02 0.35, STD-IAM-04 0.348, STD-DATA-01 0.348
- prompt_injection (embedding): STD-IAM-04 0.379, STD-CHG-01 0.378, STD-K8S-01 0.349, STD-CHG-02 0.346
- secret_in_values (embedding): STD-CHG-01 0.384, STD-CHG-02 0.373, STD-DATA-01 0.351, STD-IAM-04 0.332
