# EconomicBridge — Elastic Container Registry.
#
# One ECR repo per microservice (api, ingestion, ml, notifications, frontend).
# GitHub Actions builds → tags → pushes here, and ECS pulls from here on
# every task deployment.

resource "aws_ecr_repository" "service" {
  for_each = local.services

  name = "${local.name_prefix}/${each.key}"
  # MUTABLE because the deploy flow uses a moving `latest` tag: task defs pin
  # :latest and deploy.yml rolls services with --force-new-deployment. With
  # IMMUTABLE, the second-ever deploy fails ("tag 'latest' ... cannot be
  # overwritten"). Provenance still holds — every build also pushes the
  # commit-SHA tag, which is never reused.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true # Trivy-equivalent scan; results visible in console
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
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 20
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
