terraform {
  required_version = "~> 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69"
    }
  }

  backend "s3" {
    bucket       = "tf-state-590183753633"
    key          = "bedrock-terraform-reviewer/terraform.tfstate"
    region       = "us-west-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-west-1"

  default_tags {
    tags = {
      Project   = "bedrock-terraform-reviewer"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# The GitHub OIDC provider already exists (created by Project 1's bootstrap).
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Immutable IDs, so a renamed or recreated repo can't assume this role (story 52).
  owner         = "YoungMaster009"
  owner_id      = "145816778"
  p1_repo       = "terraform-aws-portfolio"
  p1_repo_id    = "1385934191"
  p1_pr_subject = "repo:${local.owner}@${local.owner_id}/${local.p1_repo}@${local.p1_repo_id}:pull_request"

  # Nova Lite, called through the US cross-Region inference profile.
  inference_profile_arn = "arn:aws:bedrock:us-west-1:${local.account_id}:inference-profile/us.amazon.nova-lite-v1:0"
  model_arn             = "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0"
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Exact match: pull requests in the Project 1 repo only.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.p1_pr_subject]
    }
  }
}

resource "aws_iam_role" "plan_reviewer" {
  name                 = "github-actions-plan-reviewer"
  description          = "Lets Project 1 pull requests call Nova Lite on Bedrock, nothing else"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "bedrock" {
  # Call the inference profile in our home region.
  statement {
    sid       = "InvokeNovaLiteProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.inference_profile_arn]
  }

  # The profile routes to Nova Lite in other US regions, so the model ARN needs a
  # wildcard region. The condition means it's only reachable through our profile.
  statement {
    sid       = "InvokeNovaLiteOnlyViaProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.model_arn]

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.inference_profile_arn]
    }
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "invoke-nova-lite-only"
  role   = aws_iam_role.plan_reviewer.id
  policy = data.aws_iam_policy_document.bedrock.json
}

output "plan_reviewer_role_arn" {
  value = aws_iam_role.plan_reviewer.arn
}
