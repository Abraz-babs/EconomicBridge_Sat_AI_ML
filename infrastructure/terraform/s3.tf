# EconomicBridge — S3 artifacts bucket.
#
# Holds large runtime artifacts that can't ship in git or Docker images —
# first user: the trained CropGuard ResNet-50 weights (~94 MB, gitignored).
# The ml service downloads s3://<bucket>/ml/crop_classifier.pth at startup
# (MODEL_S3_URI env), so the image stays slim and CI never needs the binary.

resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.name_prefix}-artifacts-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${local.name_prefix}-artifacts"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

output "artifacts_bucket" {
  value       = aws_s3_bucket.artifacts.bucket
  description = "S3 bucket for large runtime artifacts (ML model weights)."
}

# ─── ALB access logs ───────────────────────────────────────────────────────
#
# WHY (2026-08-24). The Zayed Selection Committee sat 17-20 Aug and the
# operator wanted to know whether they had opened the platform. We could not
# tell: access logs were off, the frontend logs only errors, and no client IP
# is captured anywhere. Container request volume is ~53k/day and almost
# entirely ALB health checks, so a handful of human page views is invisible
# inside it.
#
# The Jury sits 15 Sep and finalists are announced 23 Sep. Turning this on now
# means those are answerable: access logs carry client IP, path, user agent and
# referrer per request.
#
# Reuses the existing artifacts bucket under an alb-logs/ prefix rather than
# creating another bucket — one fewer thing to name, secure and pay for.
data "aws_elb_service_account" "main" {}

data "aws_iam_policy_document" "alb_logs" {
  # ELB in older regions writes as a service ACCOUNT principal; newer regions
  # use the service principal. eu-west-1 is an older region, so the account
  # form is the one that works — granting both would be a policy that looks
  # right and silently never matches.
  statement {
    sid    = "AllowALBLogDelivery"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.main.arn]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/alb-logs/*"]
  }
}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.alb_logs.json
}

# Access logs are a visitor record, not an archive: 90 days answers "did they
# look, and when" across a prize cycle without accumulating personal data
# indefinitely.
resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-alb-logs"
    status = "Enabled"

    filter {
      prefix = "alb-logs/"
    }

    expiration {
      days = 90
    }
  }
}
