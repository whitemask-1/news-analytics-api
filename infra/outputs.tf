# =============================================================================
# TERRAFORM OUTPUTS
# =============================================================================
# These values are displayed after deployment and can be queried with:
# terraform output <output_name>

# =============================================================================
# API GATEWAY
# =============================================================================

output "api_gateway_url" {
  description = "Base URL for the API Gateway endpoint"
  value       = aws_apigatewayv2_api.http_api.api_endpoint
}

# =============================================================================
# LAMBDA FUNCTIONS
# =============================================================================

output "api_lambda_function_name" {
  description = "Name of the API Lambda function"
  value       = aws_lambda_function.api_handler.function_name
}

output "worker_lambda_function_name" {
  description = "Name of the Worker Lambda function"
  value       = aws_lambda_function.worker.function_name
}

output "api_lambda_arn" {
  description = "ARN of the API Lambda function"
  value       = aws_lambda_function.api_handler.arn
}

output "worker_lambda_arn" {
  description = "ARN of the Worker Lambda function"
  value       = aws_lambda_function.worker.arn
}

# =============================================================================
# SQS QUEUES
# =============================================================================

output "sqs_queue_url" {
  description = "URL of the SQS ingestion queue"
  value       = aws_sqs_queue.ingest_queue.url
}

output "sqs_dlq_url" {
  description = "URL of the SQS dead letter queue"
  value       = aws_sqs_queue.ingest_dlq.url
}

# =============================================================================
# S3 BUCKETS
# =============================================================================

output "s3_bucket_raw_name" {
  description = "Name of the S3 bucket for raw articles"
  value       = aws_s3_bucket.raw_articles.bucket
}

output "s3_bucket_normalized_name" {
  description = "Name of the S3 bucket for normalized articles"
  value       = aws_s3_bucket.normalized_articles.bucket
}

output "s3_bucket_athena_name" {
  description = "Name of the S3 bucket for Athena query results"
  value       = aws_s3_bucket.athena_results.bucket
}

# =============================================================================
# ECR REPOSITORY
# =============================================================================

output "ecr_repository_url" {
  description = "URL of the ECR repository for Docker images"
  value       = aws_ecr_repository.app.repository_url
}

# =============================================================================
# SECRETS MANAGER
# =============================================================================

output "secrets_configured" {
  description = "List of secrets configured in AWS Secrets Manager"
  value = [
    aws_secretsmanager_secret.news_api_key.name,
    aws_secretsmanager_secret.upstash_redis_url.name,
    aws_secretsmanager_secret.upstash_redis_token.name
  ]
}

# =============================================================================
# ATHENA
# =============================================================================

output "athena_database_name" {
  description = "Name of the Athena/Glue database"
  value       = aws_glue_catalog_database.news_analytics.name
}

output "athena_table_name" {
  description = "Name of the Athena table for normalized articles"
  value       = aws_glue_catalog_table.normalized_articles.name
}

output "athena_workgroup_name" {
  description = "Name of the Athena workgroup"
  value       = aws_athena_workgroup.news_analytics.name
}

# =============================================================================
# DEPLOYMENT SUMMARY
# =============================================================================

output "deployment_summary" {
  description = "Summary of deployed resources"
  value = {
    api_endpoint     = "${aws_apigatewayv2_api.http_api.api_endpoint}/health"
    ingest_endpoint  = "${aws_apigatewayv2_api.http_api.api_endpoint}/api/v1/ingest"
    docs_endpoint    = "${aws_apigatewayv2_api.http_api.api_endpoint}/docs"
    environment      = var.environment
    region           = var.aws_region
    project_name     = var.project_name
  }
}
