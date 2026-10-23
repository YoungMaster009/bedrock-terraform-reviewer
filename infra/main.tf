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

  # Every model is called through a US cross-Region inference profile. This account's
  # direct (single-Region) quotas are 0; its cross-Region quotas are not.
  models = {
    nova_lite    = "amazon.nova-lite-v1:0" # writes the review
    cohere_embed = "cohere.embed-v4:0"     # embeds standards for retrieval (RAG)
  }
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
  description          = "Lets Project 1 pull requests call two Bedrock models, nothing else"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "bedrock" {
  # Call each model's US inference profile in our home region.
  dynamic "statement" {
    for_each = local.models
    content {
      sid       = "Invoke${replace(title(replace(statement.key, "_", " ")), " ", "")}Profile"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:aws:bedrock:us-west-1:${local.account_id}:inference-profile/us.${statement.value}"]
    }
  }

  # The profile routes to the model in other US Regions, so the model ARN needs a wildcard
  # Region. The condition means each model is only reachable through its own profile.
  dynamic "statement" {
    for_each = local.models
    content {
      sid       = "Invoke${replace(title(replace(statement.key, "_", " ")), " ", "")}OnlyViaProfile"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:aws:bedrock:*::foundation-model/${statement.value}"]

      condition {
        test     = "StringEquals"
        variable = "bedrock:InferenceProfileArn"
        values   = ["arn:aws:bedrock:us-west-1:${local.account_id}:inference-profile/us.${statement.value}"]
      }
    }
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "invoke-approved-bedrock-models"
  role   = aws_iam_role.plan_reviewer.id
  policy = data.aws_iam_policy_document.bedrock.json
}

output "plan_reviewer_role_arn" {
  value = aws_iam_role.plan_reviewer.arn
}
