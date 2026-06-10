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
