# EconomicBridge — Elastic Container Registry.
#
# One ECR repo per microservice (api, ingestion, ml, notifications, frontend).
# GitHub Actions builds → tags → pushes here, and ECS pulls from here on
# every task deployment.

resource "aws_ecr_repository" "service" {
  for_each = local.services

  name                 = "${local.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"  # never overwrite a tag (e.g. `latest`)

  image_scanning_configuration {
    scan_on_push = true  # Trivy-equivalent scan; results visible in console
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name    = "${local.name_prefix}-${each.key}-ecr"
    Service = each.key
  }
}

# Lifecycle policy: keep the latest 20 images per repo, expire untagged
# after 7 days. Stops the bill from drifting on stale layers.
resource "aws_ecr_lifecycle_policy" "service" {
  for_each = aws_ecr_repository.service

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 20 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPatternList = ["*"]
          countType     = "imageCountMoreThan"
          countNumber   = 20
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}
