# =============================================================================
# IAM (Identity and Access Management)
# =============================================================================
# IAM controls WHO can do WHAT in AWS
# For ECS, we need TWO types of roles:
# 1. Task Execution Role - What ECS itself needs (pull images, write logs)
# 2. Task Role - What YOUR application needs (access S3, call other AWS services)

# =============================================================================
# TASK EXECUTION ROLE
# =============================================================================
# This role is used BY ECS to set up your container
# ECS needs permission to:
# - Pull Docker images from ECR
# - Write logs to CloudWatch
# - Get secrets from Secrets Manager (if you use it)

# -----------------------------------------------------------------------------
# Assume Role Policy Document
# -----------------------------------------------------------------------------
# "Assume Role" = Who is allowed to USE this role
# We're saying: "ECS tasks service can use this role"

data "aws_iam_policy_document" "ecs_task_execution_assume_role" {
  # data source: Read-only, doesn't create resources
  # Fetches or generates information
  
  statement {
    actions = ["sts:AssumeRole"]
    # sts = Security Token Service
    # AssumeRole = temporarily become this role
    
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
      # Only the ECS service can assume this role
      # Not users, not other services
    }
  }
}

# -----------------------------------------------------------------------------
# Task Execution Role Resource
# -----------------------------------------------------------------------------

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.project_name}-${var.environment}-ecs-task-execution-role"
  
  # assume_role_policy: JSON document defining who can use this role
  # Reference the data source we defined above
  assume_role_policy = data.aws_iam_policy_document.ecs_task_execution_assume_role.json

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-ecs-task-execution-role"
    }
  )
}

# -----------------------------------------------------------------------------
# Attach AWS Managed Policy
# -----------------------------------------------------------------------------
# AWS provides pre-made policies for common use cases
# "AmazonECSTaskExecutionRolePolicy" includes:
# - ecr:GetAuthorizationToken (login to ECR)
# - ecr:BatchCheckLayerAvailability (check image exists)
# - ecr:GetDownloadUrlForLayer (get image layers)
# - ecr:BatchGetImage (download image)
# - logs:CreateLogStream (create log streams)
# - logs:PutLogEvents (write logs)

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  # policy_arn: Amazon Resource Name for the policy
  # "aws:policy" = AWS-managed (not your account-specific)
}

# =============================================================================
# TASK ROLE
# =============================================================================
# This role is used BY YOUR APPLICATION while it's running
# Your FastAPI app will use this role to access AWS services
# Examples:
# - Read/write to S3 buckets
# - Query Athena
# - Get secrets from Secrets Manager
# - Send metrics to CloudWatch

# -----------------------------------------------------------------------------
# Assume Role Policy for Task Role
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# -----------------------------------------------------------------------------
# Task Role Resource
# -----------------------------------------------------------------------------

resource "aws_iam_role" "ecs_task_role" {
  name               = "${var.project_name}-${var.environment}-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-ecs-task-role"
    }
  )
}

# -----------------------------------------------------------------------------
# Custom Policy for Application Permissions
# -----------------------------------------------------------------------------
# Define exactly what your application can do

data "aws_iam_policy_document" "ecs_task_policy" {
  # Statement 1: S3 Access
  # Your app writes news articles to S3
  statement {
    sid    = "S3Access"
    # sid = Statement ID (for documentation)
    effect = "Allow"
    # Allow or Deny
    
    actions = [
      "s3:PutObject",
      # Upload files to S3
      "s3:GetObject",
      # Download files from S3
      "s3:ListBucket",
      # List files in bucket
      "s3:DeleteObject"
      # Delete files (optional)
    ]
    
    resources = [
      "arn:aws:s3:::${var.project_name}-${var.environment}-*",
      # Bucket ARN pattern
      "arn:aws:s3:::${var.project_name}-${var.environment}-*/*"
      # Objects in bucket (note the /*)
    ]
  }
  
  # Statement 2: CloudWatch Logs
  # Your app writes custom application logs
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams"
    ]
    
    resources = ["arn:aws:logs:*:*:*"]
    # All logs (could be more restrictive)
  }
  
  # Statement 3: Athena Access
  # Your app queries news data with Athena
  statement {
    sid    = "AthenaAccess"
    effect = "Allow"
    
    actions = [
      "athena:StartQueryExecution",
      # Run queries
      "athena:GetQueryExecution",
      # Check query status
      "athena:GetQueryResults",
      # Get query results
      "athena:StopQueryExecution"
      # Cancel queries
    ]
    
    resources = ["*"]
    # Athena requires wildcard for some operations
  }
  
  # Statement 4: Glue Access (for Athena catalog)
  # Athena uses Glue as its metadata catalog
  statement {
    sid    = "GlueAccess"
    effect = "Allow"
    
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetPartitions"
    ]
    
    resources = ["*"]
  }

  # Statement 5: Secrets Manager (Optional)
  # If you want to store API keys in Secrets Manager instead of env vars
  statement {
    sid    = "SecretsManagerAccess"
    effect = "Allow"
    
    actions = [
      "secretsmanager:GetSecretValue"
      # Read secret values
    ]
    
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.project_name}/${var.environment}/*"
      # Only secrets matching your project pattern
    ]
  }
}

# -----------------------------------------------------------------------------
# Create the IAM Policy from the Document
# -----------------------------------------------------------------------------

resource "aws_iam_policy" "ecs_task_policy" {
  name        = "${var.project_name}-${var.environment}-ecs-task-policy"
  description = "Policy for ECS tasks to access required AWS services"
  
  # policy: Convert the policy document to JSON
  policy = data.aws_iam_policy_document.ecs_task_policy.json
}

# -----------------------------------------------------------------------------
# Attach the Policy to the Task Role
# -----------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "ecs_task_policy" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_policy.arn
  # This time it's YOUR policy, so it has your account ID in the ARN
}

# =============================================================================
# CLOUDWATCH LOG GROUP
# =============================================================================
# Where your container logs will be stored
# ECS automatically sends stdout/stderr here

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}-${var.environment}"
  retention_in_days = 7
  # Keep logs for 7 days (cost optimization)
  # Options: 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653
  # Longer retention = higher cost

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-ecs-logs"
    }
  )
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "ecs_task_execution_role_arn" {
  description = "ARN of the ECS task execution role"
  value       = aws_iam_role.ecs_task_execution_role.arn
  # Used in ECS task definition
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task role"
  value       = aws_iam_role.ecs_task_role.arn
  # Used in ECS task definition
}

output "cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group"
  value       = aws_cloudwatch_log_group.ecs.name
  # Used in ECS task definition
}
