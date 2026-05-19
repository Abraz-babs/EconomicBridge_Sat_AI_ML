# EconomicBridge — Terraform + provider version pins.
#
# Re-running `terraform init` after a major version bump may require state
# upgrades. Bump these carefully and bracket with a `terraform plan` to verify
# nothing in state structure shifted.

terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
