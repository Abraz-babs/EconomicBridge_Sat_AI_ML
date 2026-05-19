# EconomicBridge — AWS provider configuration.
#
# Region is variable-driven so staging (eu-west-1) and production
# (af-south-1) deploy from the same code. The default_tags block stamps
# every resource so cost-explorer can group by Environment / Module —
# critical when the bill arrives.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "EconomicBridge"
      ManagedBy   = "Terraform"
      Environment = var.environment
      Owner       = "Bizra Farms"
      Repository  = "github.com/Abraz-babs/EconomicBridge_Sat_AI_ML"
    }
  }
}
