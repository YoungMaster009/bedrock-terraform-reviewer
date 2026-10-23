# Infrastructure Standards

Each standard has an ID the reviewer cites in pull-request comments. One standard per section, so each
section can be embedded and retrieved on its own.

## STD-NET-01: No admin ports open to the internet
Rule: Security groups must never allow SSH (22) or RDP (3389) from 0.0.0.0/0 or ::/0.
Why: Open admin ports are scanned and brute-forced within minutes of going live.
Fix: Use AWS Systems Manager Session Manager for shell access, or limit the source to a known private range.

## STD-NET-02: Only load balancers face the internet
Rule: Application servers run in private subnets and accept traffic only from the load balancer's security group.
Why: Keeps every server off the public internet; the load balancer is the single, hardened entry point.
Fix: Put instances in private subnets and reference the load balancer security group as the ingress source.

## STD-DATA-01: Protect stateful resources from deletion
Rule: Databases, buckets, tables, and volumes need deletion protection or lifecycle prevent_destroy.
Why: A delete or a forced replacement destroys the data along with the resource.
Fix: Enable deletion_protection, add lifecycle { prevent_destroy = true }, and take a snapshot before any planned replacement.

## STD-DATA-02: S3 buckets stay private
Rule: All four S3 Block Public Access settings stay on. No public ACLs. No bucket policy that allows Principal "*" without a condition.
Why: Public buckets are one of the most common causes of data leaks.
Fix: Serve public content through CloudFront with Origin Access Control instead of making the bucket public.

## STD-DATA-03: Encrypt data at rest
Rule: S3 buckets, EBS volumes, and RDS databases use encryption at rest.
Why: Protects data if storage is ever exposed and is required by most compliance frameworks.
Fix: Use SSE-S3 or SSE-KMS for buckets, set encrypted = true on volumes, and storage_encrypted = true on databases.

## STD-IAM-01: No wildcard admin permissions
Rule: No policy may allow Action "*" on Resource "*", and automation must never use AdministratorAccess.
Why: A leaked credential with admin access can take over the whole account.
Fix: List the specific actions needed and scope them to specific resource ARNs; prove the policy with a full apply and destroy.

## STD-IAM-02: CI/CD uses OIDC, never stored keys
Rule: Pipelines authenticate to AWS with OIDC. Role trust policies match the exact sub claim using immutable repository and owner IDs.
Why: Long-lived access keys leak; trust on repository names breaks if a repo is renamed or recreated.
Fix: Use GitHub's OIDC provider with StringEquals on the full sub claim, confirmed from a real CloudTrail event.

## STD-IAM-03: Roles that create roles need guardrails
Rule: Any role allowed to create IAM roles may only attach an approved list of policies, only to roles with an approved name prefix.
Why: Without guardrails, a role that can create roles can create itself an administrator (privilege escalation).
Fix: Add iam:PolicyARN conditions on attach actions, limit role names with a prefix, and restrict iam:PassRole to one service.

## STD-IAM-04: Review policies that can't be checked at plan time
Rule: If a policy is only known after apply, a human reviews the applied policy before the change reaches production.
Why: Automated checks can't see what isn't in the plan yet.
Fix: After apply, read the policy with aws iam get-role-policy, or plan again against the existing environment where the ARNs are known.

## STD-CHG-01: Plan replacements without downtime
Rule: Replacing running compute must not drop traffic.
Why: A replace destroys the old resource; without care, users see errors during the gap.
Fix: Use create_before_destroy, rolling instance refresh for Auto Scaling groups, and check which attribute forces the replacement before approving.

## STD-CHG-02: Read every plan before apply
Rule: Every change is planned in a pull request and reviewed before apply. Each environment has its own state.
Why: A plan review once caught prod pointed at dev state before any damage was done.
Fix: Require the plan check on protected branches and keep separate state keys per environment.

## STD-COST-01: Nothing non-production runs by default
Rule: Non-production environments are destroyed automatically every night, and every account has a budget alert.
Why: Forgotten test environments are the most common source of surprise bills.
Fix: Schedule a nightly destroy workflow and alert at 80 percent of the monthly budget.

## STD-TAG-01: Tag every resource
Rule: All resources carry Project, Environment, and ManagedBy tags.
Why: Tags make cost reports, ownership, and cleanup possible.
Fix: Set them once with default_tags in the AWS provider block.

## STD-K8S-01: Delete Kubernetes-owned resources before Terraform destroy
Rule: Load balancers and other resources created by Kubernetes are removed before running terraform destroy.
Why: Terraform doesn't know they exist, so destroy hangs on the VPC or leaves billing resources behind.
Fix: Delete DNS records first, then the Kubernetes Service, wait for the load balancer to disappear, then destroy.
