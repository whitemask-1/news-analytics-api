# =============================================================================
# PROJECT CONFIGURATION
# =============================================================================
# These variables define the core identity of your project

variable "project_name" {
  description = "Name of the project - used as a prefix for all resources"
  type        = string
  default     = "news-analytics"
  # This will create resources like: news-analytics-api, news-analytics-cluster
  # Makes it easy to identify your resources in AWS console
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  # Best practice: use different environments to test before production
  # Creates resources like: news-analytics-dev, news-analytics-prod
}

# =============================================================================
# AWS CONFIGURATION
# =============================================================================

variable "aws_region" {
  description = "AWS region where all resources will be created"
  type        = string
  default     = "us-east-1"
  # us-east-1 is often cheapest and has all services
  # Other options: us-west-2, eu-west-1, etc.
}

# =============================================================================
# CONTAINER CONFIGURATION
# =============================================================================
# These variables control how your Docker container runs in ECS

variable "container_port" {
  description = "Port your FastAPI application listens on"
  type        = number
  default     = 8000
  # Must match the EXPOSE port in your Dockerfile
}

variable "container_cpu" {
  description = "CPU units for the container (1024 = 1 vCPU)"
  type        = number
  default     = 256
  # Valid Fargate values: 256, 512, 1024, 2048, 4096
  # 256 = 0.25 vCPU - good for light workloads
}

variable "container_memory" {
  description = "Memory in MB for the container"
  type        = number
  default     = 512
  # Must be compatible with CPU:
  # 256 CPU: 512, 1024, or 2048 MB
  # 512 CPU: 1024 to 4096 MB
  # See: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
}

variable "desired_count" {
  description = "Number of container instances to run"
  type        = number
  default     = 1
  # Start with 1 for development
  # Increase for production (2+ for high availability)
}

# =============================================================================
# NETWORKING CONFIGURATION
# =============================================================================

variable "availability_zones" {
  description = "List of availability zones to use for high availability"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
  # Multiple AZs = high availability (if one data center fails, another takes over)
  # Must match your aws_region
}

# =============================================================================
# ENVIRONMENT VARIABLES FOR THE APPLICATION
# =============================================================================
# These are passed to your FastAPI container

variable "newsapi_key" {
  description = "API key for NewsAPI service"
  type        = string
  sensitive   = true
  # sensitive = true means Terraform won't display this in logs
  # You'll provide this when running: terraform apply -var="newsapi_key=your_key"
}

variable "log_level" {
  description = "Logging level for the application"
  type        = string
  default     = "INFO"
  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
}

# =============================================================================
# COST OPTIMIZATION
# =============================================================================

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnet internet access (costs ~$30/month)"
  type        = bool
  default     = false
  # false = use public subnets (cheaper but less secure)
  # true = use private subnets with NAT Gateway (more secure but costs money)
  # For learning/dev: set to false
}

variable "enable_container_insights" {
  description = "Enable CloudWatch Container Insights for detailed monitoring (additional cost)"
  type        = bool
  default     = false
  # true = detailed metrics and logs (easier debugging but costs more)
  # false = basic monitoring only
}

# =============================================================================
# LAMBDA & API CONFIGURATION
# =============================================================================

variable "news_api_base_url" {
  description = "Base URL for NewsAPI"
  type        = string
  default     = "https://newsapi.org/v2"
}

variable "news_api_key" {
  description = "API key for NewsAPI (should be moved to Secrets Manager in production)"
  type        = string
  sensitive   = true
  # Set via environment variable: TF_VAR_news_api_key=your_key_here
  # Or pass via -var flag: terraform apply -var="news_api_key=your_key"
}

variable "upstash_redis_url" {
  description = "Upstash Redis REST API URL"
  type        = string
  sensitive   = true
  # Get from Upstash console after creating database
  # Format: https://your-db.upstash.io
}

variable "upstash_redis_token" {
  description = "Upstash Redis REST API token"
  type        = string
  sensitive   = true
  # Get from Upstash console - authentication token for REST API
}

# =============================================================================
# TAGS
# =============================================================================
# Tags help organize and track costs in AWS

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "NewsAnalytics"
    ManagedBy   = "Terraform"
    Environment = "dev"
  }
  # Tags appear in AWS console and billing reports
  # Good practice: always tag your resources
}
