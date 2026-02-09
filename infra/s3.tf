# =============================================================================
# S3 BUCKETS FOR ARTICLE STORAGE
# =============================================================================
# This file defines S3 storage for the news analytics pipeline:
# 1. Raw bucket: Original NewsAPI responses (JSON) - temp storage for debugging
# 2. Normalized bucket: Processed articles (Parquet) - permanent storage for analytics
# 3. Athena results bucket: Query results cache

# =============================================================================
# RAW ARTICLES BUCKET
# =============================================================================

# Stores original JSON responses from NewsAPI
# Purpose: Debugging, audit trail, reprocessing if normalization logic changes
# Lifecycle: Auto-delete after 7 days (cost optimization)
resource "aws_s3_bucket" "raw_articles" {
  bucket = "${var.project_name}-${var.environment}-raw-articles"

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-raw-articles"
    Description = "Raw JSON articles from NewsAPI - temporary storage"
    DataType    = "raw-json"
  })
}

# Block all public access (security best practice)
resource "aws_s3_bucket_public_access_block" "raw_articles" {
  bucket = aws_s3_bucket.raw_articles.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable versioning for accidental deletion recovery
resource "aws_s3_bucket_versioning" "raw_articles" {
  bucket = aws_s3_bucket.raw_articles.id

  versioning_configuration {
    status = "Disabled" # Disabled to save costs (raw data is temporary)
  }
}

# Server-side encryption (security requirement)
resource "aws_s3_bucket_server_side_encryption_configuration" "raw_articles" {
  bucket = aws_s3_bucket.raw_articles.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # AWS-managed encryption (no KMS costs)
    }
  }
}

# Lifecycle policy: Delete raw files after 7 days
# Cost optimization: Raw data only needed for short-term debugging
resource "aws_s3_bucket_lifecycle_configuration" "raw_articles" {
  bucket = aws_s3_bucket.raw_articles.id

  rule {
    id     = "delete-old-raw-articles"
    status = "Enabled"

    # Apply to all objects
    filter {}

    # Delete files older than 7 days
    expiration {
      days = 7
    }

    # Also delete incomplete multipart uploads (cleanup)
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# =============================================================================
# NORMALIZED ARTICLES BUCKET
# =============================================================================

# Stores processed articles in Parquet format for Athena analytics
# Purpose: Long-term storage, efficient querying, data lake
# Lifecycle: Keep indefinitely (this is our source of truth)
resource "aws_s3_bucket" "normalized_articles" {
  bucket = "${var.project_name}-${var.environment}-normalized-articles"

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-normalized-articles"
    Description = "Normalized articles in Parquet format - permanent storage"
    DataType    = "parquet"
  })
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "normalized_articles" {
  bucket = aws_s3_bucket.normalized_articles.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning disabled (Parquet files are immutable, no updates)
resource "aws_s3_bucket_versioning" "normalized_articles" {
  bucket = aws_s3_bucket.normalized_articles.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "normalized_articles" {
  bucket = aws_s3_bucket.normalized_articles.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lifecycle policy: Transition to cheaper storage classes over time
resource "aws_s3_bucket_lifecycle_configuration" "normalized_articles" {
  bucket = aws_s3_bucket.normalized_articles.id

  rule {
    id     = "transition-to-cheaper-storage"
    status = "Enabled"

    # Apply to all objects
    filter {}

    # Move to Infrequent Access after 30 days (50% cost reduction)
    # Athena can still query IA storage
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    # Move to Glacier after 90 days (80% cost reduction)
    # For historical data rarely queried
    transition {
      days          = 90
      storage_class = "GLACIER_IR" # Instant Retrieval - no waiting for queries
    }

    # Optional: Deep archive after 1 year
    # transition {
    #   days          = 365
    #   storage_class = "DEEP_ARCHIVE"
    # }
  }
}

# =============================================================================
# ATHENA RESULTS BUCKET
# =============================================================================

# Stores Athena query results and metadata
# Required: Athena needs a bucket to write query results
resource "aws_s3_bucket" "athena_results" {
  bucket = "${var.project_name}-${var.environment}-athena-results"

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-athena-results"
    Description = "Athena query results and execution metadata"
    DataType    = "query-results"
  })
}

# Block public access
resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning disabled
resource "aws_s3_bucket_versioning" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lifecycle: Delete query results after 30 days
# Query results are cached but not needed long-term
resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "delete-old-query-results"
    status = "Enabled"

    # Apply to all objects
    filter {}

    expiration {
      days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "raw_bucket_name" {
  description = "Name of the raw articles S3 bucket"
  value       = aws_s3_bucket.raw_articles.id
}

output "raw_bucket_arn" {
  description = "ARN of the raw articles S3 bucket"
  value       = aws_s3_bucket.raw_articles.arn
}

output "normalized_bucket_name" {
  description = "Name of the normalized articles S3 bucket"
  value       = aws_s3_bucket.normalized_articles.id
}

output "normalized_bucket_arn" {
  description = "ARN of the normalized articles S3 bucket"
  value       = aws_s3_bucket.normalized_articles.arn
}

output "athena_results_bucket_name" {
  description = "Name of the Athena results S3 bucket"
  value       = aws_s3_bucket.athena_results.id
}

output "athena_results_bucket_arn" {
  description = "ARN of the Athena results S3 bucket"
  value       = aws_s3_bucket.athena_results.arn
}
