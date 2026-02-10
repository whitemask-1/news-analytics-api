# =============================================================================
# LAMBDA CONTAINER INFRASTRUCTURE
# =============================================================================
# This file defines the serverless Lambda architecture for the news analytics API
# Architecture: API Gateway -> Lambda API Handler -> SQS -> Lambda Worker -> Redis/S3
# Benefits: Pay-per-use (vs always-on ECS), auto-scales 0-1000+, no infrastructure mgmt

# =============================================================================
# SQS QUEUE FOR ASYNC ARTICLE INGESTION
# =============================================================================

# Main queue: Receives ingest requests from API Lambda
# Worker Lambda processes messages asynchronously
resource "aws_sqs_queue" "ingest_queue" {
  name                       = "${var.project_name}-${var.environment}-ingest-queue"
  visibility_timeout_seconds = 90 # Must be >= Lambda timeout (60s) + buffer
  message_retention_seconds  = 86400 # 24 hours - plenty of time for retries
  receive_wait_time_seconds  = 20 # Long polling reduces empty receives
  
  # Dead Letter Queue configuration
  # After 3 failed processing attempts, move message to DLQ for investigation
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 3 # Fail after 3 attempts (transient errors should resolve)
  })

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-ingest-queue"
    Description = "Queue for async article ingestion requests"
  })
}

# Dead Letter Queue: Captures failed messages after max retries
# CloudWatch alarm monitors this queue for troubleshooting
resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.project_name}-${var.environment}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days - keep for debugging

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-ingest-dlq"
    Description = "Dead letter queue for failed ingestion messages"
  })
}

# =============================================================================
# CLOUDWATCH ALARM FOR DLQ MONITORING
# =============================================================================

# Triggers when any message lands in DLQ (indicates processing failure)
# Sends notification to SNS topic for immediate investigation
resource "aws_cloudwatch_metric_alarm" "dlq_alarm" {
  alarm_name          = "${var.project_name}-${var.environment}-dlq-messages"
  alarm_description   = "Alert when messages appear in DLQ after failed processing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60 # Check every minute
  statistic           = "Average"
  threshold           = 0 # Alert on ANY message in DLQ
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.ingest_dlq.name
  }

  # TODO: Connect to SNS topic for email/Slack notifications
  # alarm_actions = [aws_sns_topic.alerts.arn]

  tags = var.tags
}

# =============================================================================
# IAM ROLE FOR LAMBDA EXECUTION
# =============================================================================

# Execution role: Permissions Lambda service needs to run your code
# Used by BOTH API and Worker Lambdas (they have same permission needs)
resource "aws_iam_role" "lambda_execution" {
  name               = "${var.project_name}-${var.environment}-lambda-execution"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-lambda-execution"
    Description = "Execution role for Lambda functions"
  })
}

# Trust policy: Allows Lambda service to assume this role
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Attach AWS managed policy for basic Lambda execution (CloudWatch logs)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy: Application-specific permissions
resource "aws_iam_role_policy" "lambda_permissions" {
  name   = "${var.project_name}-${var.environment}-lambda-policy"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  # S3: Store and retrieve articles (raw and normalized)
  statement {
    sid    = "S3Access"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:DeleteObject"
    ]
    resources = [
      "arn:aws:s3:::${var.project_name}-${var.environment}-*",
      "arn:aws:s3:::${var.project_name}-${var.environment}-*/*"
    ]
  }

  # SQS: Send messages to ingest queue (API Lambda) and receive/delete (Worker Lambda)
  statement {
    sid    = "SQSAccess"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [
      aws_sqs_queue.ingest_queue.arn,
      aws_sqs_queue.ingest_dlq.arn
    ]
  }

  # Athena: Execute queries for analytics
  statement {
    sid    = "AthenaAccess"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution"
    ]
    resources = ["*"] # Athena doesn't support resource-level permissions
  }

  # Glue: Access data catalog for Athena queries
  statement {
    sid    = "GlueAccess"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetPartitions"
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.project_name}_${var.environment}",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.project_name}_${var.environment}/*"
    ]
  }

  # Secrets Manager: Retrieve NewsAPI key and Upstash Redis credentials
  statement {
    sid    = "SecretsAccess"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/${var.environment}/*"
    ]
  }

  # CloudWatch Logs: Create log streams and write logs (redundant with basic execution but explicit)
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
  }
}

# Get current AWS account ID for IAM resource ARNs
data "aws_caller_identity" "current" {}

# =============================================================================
# LAMBDA FUNCTION: API HANDLER
# =============================================================================

# API Handler: Receives HTTP requests from API Gateway
# Responsibilities: Health checks, validate ingest requests, publish to SQS, serve analytics
# Uses Mangum to adapt FastAPI to Lambda event format
resource "aws_lambda_function" "api_handler" {
  function_name = "${var.project_name}-${var.environment}-api"
  role          = aws_iam_role.lambda_execution.arn
  
  # Container image configuration
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.app.repository_url}:latest"
  
  # Override CMD in Dockerfile to use API handler
  image_config {
    command = ["app.lambda_api_handler.handler"]
  }

  # Resource allocation
  memory_size = 256  # MB - lightweight API doesn't need much
  timeout     = 10   # Seconds - API responses should be fast
  
  # Environment variables for runtime configuration
  environment {
    variables = {
      ENVIRONMENT          = var.environment
      LOG_LEVEL            = var.log_level
      AWS_REGION_CUSTOM    = var.aws_region # AWS_REGION is reserved
      SQS_QUEUE_URL        = aws_sqs_queue.ingest_queue.url
      S3_BUCKET_NORMALIZED = "${var.project_name}-${var.environment}-normalized-articles"
      S3_BUCKET_ATHENA     = "${var.project_name}-${var.environment}-athena-results"
      NEWS_API_KEY         = var.news_api_key
      NEWS_API_BASE_URL    = var.news_api_base_url
      UPSTASH_REDIS_URL    = var.upstash_redis_url
      UPSTASH_REDIS_TOKEN  = var.upstash_redis_token
      REDIS_TTL_DAYS       = "14"
    }
  }

  # CloudWatch Logs configuration
  logging_config {
    log_format = "JSON"
    log_group  = "/aws/lambda/${var.project_name}-${var.environment}-api"
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-api"
    Description = "API Gateway handler for HTTP requests"
  })

  depends_on = [aws_cloudwatch_log_group.api_lambda_logs]
}

# CloudWatch log group for API Lambda
resource "aws_cloudwatch_log_group" "api_lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-api"
  retention_in_days = 7 # Keep logs for 1 week (cost optimization)

  tags = var.tags
}

# =============================================================================
# LAMBDA FUNCTION: INGEST WORKER
# =============================================================================

# Worker Lambda: Processes articles from SQS asynchronously
# Responsibilities: Fetch from NewsAPI, check Redis dedup, normalize, store to S3
# Triggered by SQS messages (event-driven architecture)
resource "aws_lambda_function" "worker" {
  function_name = "${var.project_name}-${var.environment}-worker"
  role          = aws_iam_role.lambda_execution.arn
  
  # Container image configuration (same image, different handler)
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.app.repository_url}:latest"
  
  # Override CMD to use worker handler
  image_config {
    command = ["app.lambda_worker_handler.handler"]
  }

  # Resource allocation - worker needs more power for processing
  memory_size = 1024 # MB - normalization + S3 writes need more memory
  timeout     = 60   # Seconds - NewsAPI calls + processing can take time
  
  # Note: Reserved concurrency removed for dev environment to avoid quota issues
  # In production, set to limit concurrent executions if needed
  # reserved_concurrent_executions = 5

  # Environment variables
  environment {
    variables = {
      ENVIRONMENT          = var.environment
      LOG_LEVEL            = var.log_level
      AWS_REGION_CUSTOM    = var.aws_region
      S3_BUCKET_RAW        = "${var.project_name}-${var.environment}-raw-articles"
      S3_BUCKET_NORMALIZED = "${var.project_name}-${var.environment}-normalized-articles"
      NEWS_API_BASE_URL    = var.news_api_base_url
      NEWS_API_KEY         = var.news_api_key # TODO: Move to Secrets Manager
      UPSTASH_REDIS_URL    = var.upstash_redis_url
      UPSTASH_REDIS_TOKEN  = var.upstash_redis_token
      REDIS_TTL_DAYS       = "14"
      SQS_QUEUE_URL        = aws_sqs_queue.ingest_queue.url
    }
  }

  # CloudWatch Logs configuration
  logging_config {
    log_format = "JSON"
    log_group  = "/aws/lambda/${var.project_name}-${var.environment}-worker"
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-worker"
    Description = "Worker Lambda for article ingestion and processing"
  })

  depends_on = [aws_cloudwatch_log_group.worker_lambda_logs]
}

# CloudWatch log group for Worker Lambda
resource "aws_cloudwatch_log_group" "worker_lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-worker"
  retention_in_days = 7

  tags = var.tags
}

# SQS trigger: Connects Worker Lambda to ingest queue
# Lambda polls queue and processes messages in batches
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.ingest_queue.arn
  function_name    = aws_lambda_function.worker.arn
  
  # Batch configuration
  batch_size                         = 1  # Process 1 message at a time (each has 100 articles)
  maximum_batching_window_in_seconds = 0  # Don't wait, process immediately
  
  # Error handling
  function_response_types = ["ReportBatchItemFailures"] # Enable partial batch failure handling
  
  # Scaling: Start with 2 concurrent pollers, scale up to reserved concurrency (5)
  scaling_config {
    maximum_concurrency = 5
  }
}

# =============================================================================
# API GATEWAY HTTP API
# =============================================================================

# API Gateway: Public HTTP endpoint for the news analytics API
# Replaces ECS ALB - simpler and cheaper for REST APIs
resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.project_name}-${var.environment}-api"
  protocol_type = "HTTP" # HTTP API is simpler/cheaper than REST API
  description   = "News Analytics API - Article ingestion and analytics"

  # CORS configuration for browser clients
  cors_configuration {
    allow_origins = ["*"] # TODO: Restrict to specific domains in production
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type", "x-api-key"]
    max_age       = 300
  }

  tags = var.tags
}

# API Gateway Stage: Deployment stage (dev, prod, etc.)
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true # Automatically deploy changes

  # Access logging for debugging and monitoring
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      errorMessage   = "$context.error.message"
    })
  }

  tags = var.tags
}

# CloudWatch log group for API Gateway access logs
resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/apigateway/${var.project_name}-${var.environment}"
  retention_in_days = 7

  tags = var.tags
}

# Lambda integration: Connects API Gateway to Lambda API handler
resource "aws_apigatewayv2_integration" "lambda" {
  api_id           = aws_apigatewayv2_api.http_api.id
  integration_type = "AWS_PROXY" # Passes full request to Lambda

  integration_uri    = aws_lambda_function.api_handler.invoke_arn
  integration_method = "POST"
  payload_format_version = "2.0" # Latest format with better structure
}

# Route: Catch-all route - FastAPI handles routing internally
resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "$default" # Catch all routes

  target = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Permission: Allow API Gateway to invoke API Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"

  # Allow from any stage of this API
  source_arn = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}

# =============================================================================
# EVENTBRIDGE SCHEDULE FOR AUTOMATIC INGESTION
# =============================================================================

# EventBridge Scheduler: Triggers worker Lambda every 6 hours
# Automatically fetches news articles on a schedule
resource "aws_cloudwatch_event_rule" "scheduled_ingestion" {
  name                = "${var.project_name}-${var.environment}-scheduled-ingestion"
  description         = "Trigger article ingestion every 6 hours"
  schedule_expression = "cron(0 */6 * * ? *)" # Every 6 hours at :00 minutes
  # Cron format: (minute hour day month day-of-week year)
  # 0 */6 * * ? * = minute 0, every 6 hours, every day

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-scheduled-ingestion"
    Description = "Scheduled article ingestion"
  })
}

# EventBridge Target: Sends message to SQS queue with query parameters
resource "aws_cloudwatch_event_target" "sqs" {
  rule      = aws_cloudwatch_event_rule.scheduled_ingestion.name
  target_id = "SendToSQS"
  arn       = aws_sqs_queue.ingest_queue.arn

  # Message payload: Flexible JSON structure for worker Lambda
  # Can add more queries by creating additional EventBridge rules
  input = jsonencode({
    query    = "artificial intelligence OR machine learning OR AI"
    limit    = 100
    language = "en"
    source   = "scheduled" # Track if message came from schedule vs API
  })
}

# Permission: Allow EventBridge to send messages to SQS
resource "aws_sqs_queue_policy" "eventbridge_to_sqs" {
  queue_url = aws_sqs_queue.ingest_queue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgeToSendMessages"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.ingest_queue.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.scheduled_ingestion.arn
          }
        }
      }
    ]
  })
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "api_gateway_url" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "sqs_queue_url" {
  description = "SQS queue URL for ingestion"
  value       = aws_sqs_queue.ingest_queue.url
}

output "lambda_api_arn" {
  description = "API Lambda function ARN"
  value       = aws_lambda_function.api_handler.arn
}

output "lambda_worker_arn" {
  description = "Worker Lambda function ARN"
  value       = aws_lambda_function.worker.arn
}
