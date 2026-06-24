# Budget Mode — cost cuts while on AWS free-plan credits

Applied **2026-06-24** to stretch the AWS free-plan credits (they were burning
~$215/mo; credits dropped $68→$32 in 5 days). The default Terraform is
**unchanged and production-safe** — budget mode is turned on only via the
(gitignored) staging `terraform.tfvars` plus one committed right-size in
`locals.tf`. **Roll back to the original setup the moment budget is in place
(see below).**

Operate everything from the CLI — **no AWS console login needed**:
profile `economicbridge` (IAM user `economicbridge-deployer`), workspace
`staging`, region `eu-west-1`, `terraform` at `~/bin/terraform.exe`.

## What budget mode changed (applied)
| Change | Where | Saving | Dashboard impact |
|---|---|---|---|
| NAT gateway removed; ECS tasks run in **public subnets** (egress via IGW; inbound still ALB-only via the task SG) | `use_nat_gateway = false` (tfvars) | ~$33/mo | **none** |
| `notifications` right-sized 0.5 vCPU/1 GB → **0.25/0.5** | `locals.tf` | ~$9/mo | **none** |
| `ml` removed from autoscaling so it *can* be parked — **left RUNNING for now** | `parked_services = ["ml"]` (tfvars) | $0 until parked | **none** |

Burn: **~$215/mo → ~$173/mo**. Verified after apply: 0 NAT gateways, all 5
services healthy (HTTP 200), `ml` running 1/1, data endpoints `success=true`.
On ~$92 credits (after claiming the +$60) that is **~16 days**.

## Optional extra saving — park `ml` (reaches ~3 weeks)
The dashboard reads predictions **from the database**, so parking `ml` keeps
every page working; only running a **new** CropGuard leaf-prediction needs it
up. Saves ~$21/mo more (→ ~$152/mo → ~3 weeks on $92).
```
# Park (between demos):
aws ecs update-service --cluster economicbridge-staging-cluster \
  --service economicbridge-staging-ml --desired-count 0 --region eu-west-1
# Un-park (before a live CropGuard demo; ~2 min to start):
aws ecs update-service --cluster economicbridge-staging-cluster \
  --service economicbridge-staging-ml --desired-count 1 --region eu-west-1
```

## ROLLBACK to the original setup (when budget is in place)
1. In `infrastructure/terraform/terraform.tfvars` set:
   - `use_nat_gateway = true`
   - `parked_services = []`
2. (Optional, to match the exact original) In `locals.tf`, `notifications`:
   `cpu = 512`, `memory = 1024`.
3. If `ml` was parked, bring it back: `... --service economicbridge-staging-ml --desired-count 1`.
4. Apply:
   ```
   $env:AWS_PROFILE='economicbridge'
   ~/bin/terraform.exe -chdir=infrastructure/terraform apply
   ```
This **recreates the NAT gateway, moves tasks back to private subnets, restores
`ml` autoscaling and full `notifications` size**. ~2–3 min rolling redeploy, no
data loss.

## Notes
- The Resend email secret (`/economicbridge/staging/resend/api_key`) was created
  and populated with the real key during this apply — email keeps working.
- The `rds.force_ssl` parameter change in the same apply was metadata only
  (`pending-reboot`→`immediate`, value unchanged) — **no DB reboot**.
