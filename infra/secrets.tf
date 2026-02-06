# =============================================================================
# AWS SECRETS MANAGER
# =============================================================================
# Store sensitive configuration values securely
# Lambda functions retrieve these at runtime via IAM permissions
# Never hardcode secrets in code or commit to git

# =============================================================================
# NEWS API KEY SECRET
# =============================================================================
# NewsAPI.org API key for fetching news articles
# Get your key from: https://newsapi.org/register

resource "aws_secretsmanager_secret" "news_api_key" {
  name        = "${var.project_name}/${var.environment}/news-api-key"
  description = "NewsAPI.org API key for fetching news articles"

  # Recovery window: Days before permanent deletion (7-30)
  # Prevents accidental deletion - can be restored during this period
  recovery_window_in_days = 7

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-news-api-key"
    }
  )
}

# Store the actual secret value
# IMPORTANT: After creating, update via:
# aws secretsmanager put-secret-value \
#   --secret-id <secret_name> \
#   --secret-string "your-actual-api-key"

resource "aws_secretsmanager_secret_version" "news_api_key" {
  secret_id     = aws_secretsmanager_secret.news_api_key.id
  secret_string = var.news_api_key
  # Will use value from terraform.tfvars or -var flag
  # For production, use AWS CLI to update after deployment
}

# =============================================================================
# UPSTASH REDIS URL SECRET
# =============================================================================
# Upstash Redis REST API endpoint URL
# Format: https://<name>.upstash.io

resource "aws_secretsmanager_secret" "upstash_redis_url" {
  name                    = "${var.project_name}/${var.environment}/upstash-redis-url"
  description             = "Upstash Redis REST API endpoint URL"
  recovery_window_in_days = 7

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-upstash-redis-url"
    }
  )
}

resource "aws_secretsmanager_secret_version" "upstash_redis_url" {
  secret_id     = aws_secretsmanager_secret.upstash_redis_url.id
  secret_string = var.upstash_redis_url
}

# =============================================================================
# UPSTASH REDIS TOKEN SECRET
# =============================================================================
# Upstash Redis authentication token
# Used in Authorization: Bearer <token> header

resource "aws_secretsmanager_secret" "upstash_redis_token" {
  name                    = "${var.project_name}/${var.environment}/upstash-redis-token"
  description             = "Upstash Redis authentication token"
  recovery_window_in_days = 7

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-upstash-redis-token"
    }
  )
}

resource "aws_secretsmanager_secret_version" "upstash_redis_token" {
  secret_id     = aws_secretsmanager_secret.upstash_redis_token.id
  secret_string = var.upstash_redis_token
}

# =============================================================================
# OUTPUTS
# =============================================================================
# Export secret ARNs for Lambda environment variables

output "news_api_key_secret_arn" {
  description = "ARN of NewsAPI key secret"
  value       = aws_secretsmanager_secret.news_api_key.arn
}

output "upstash_redis_url_secret_arn" {
  description = "ARN of Upstash Redis URL secret"
  value       = aws_secretsmanager_secret.upstash_redis_url.arn
}

output "upstash_redis_token_secret_arn" {
  description = "ARN of Upstash Redis token secret"
  value       = aws_secretsmanager_secret.upstash_redis_token.arn
}
