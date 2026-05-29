# EconomicBridge — remote state backend.
#
# State lives in the S3 bucket we created during dev-env bootstrap, with a
# DynamoDB table for locking so two concurrent `terraform apply` runs cannot
# corrupt state. The bucket + table were created out-of-band by the
# `aws s3api create-bucket` / `aws dynamodb create-table` commands documented
# in docs/PROGRESS.md (Step 12b prerequisites).
#
# To switch to a different account / region, override at init time:
#   terraform init \
#     -backend-config="bucket=other-state-bucket" \
#     -backend-config="region=eu-west-1"
#
# `key` includes the workspace so staging and prod don't collide. Use
# `terraform workspace new staging` / `terraform workspace new production`.

terraform {
  backend "s3" {
    bucket = "economicbridge-tf-state-198566079411"
    # Static key — backend config cannot use interpolation. The S3 backend
    # namespaces non-default workspaces automatically under
    # `env:/<workspace>/<key>` (workspace_key_prefix defaults to `env:`), so
    # staging and production state never collide.
    key            = "economicbridge/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "economicbridge-tf-locks"
    encrypt        = true
  }
}
