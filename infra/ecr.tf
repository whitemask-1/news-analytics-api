# =============================================================================
# ECR (Elastic Container Registry)
# =============================================================================
# ECR is AWS's private Docker registry - like Docker Hub but private to your account
# This is where you'll push your Docker images before ECS can run them

# -----------------------------------------------------------------------------
# ECR Repository Resource
# -----------------------------------------------------------------------------
# TERRAFORM SYNTAX:
# resource "resource_type" "local_name" {
#   argument = value
# }

resource "aws_ecr_repository" "app" {
  # name: The repository name (will appear in AWS console and CLI)
  # String interpolation: "${var.x}-${var.y}" combines variables
  name = "${var.project_name}-${var.environment}"
  # Result: "news-analytics-dev"
  
  # image_tag_mutability: Can you overwrite a tag?
  # MUTABLE = yes (can push over "latest" tag multiple times)
  # IMMUTABLE = no (each push needs a unique tag like v1.0.1, v1.0.2)
  image_tag_mutability = "MUTABLE"
  # MUTABLE is easier for development (reuse "latest")
  # IMMUTABLE is safer for production (can't accidentally overwrite)

  # image_scanning_configuration: Security scanning for vulnerabilities
  image_scanning_configuration {
    # scan_on_push: Automatically scan images for CVEs when pushed
    scan_on_push = true
    # AWS scans for known vulnerabilities (like outdated Python packages)
    # Results appear in ECR console - useful for security compliance
  }

  # encryption_configuration: How images are encrypted at rest
  encryption_configuration {
    # encryption_type: KMS or AES256
    # AES256 = AWS-managed encryption (free, simple)
    # KMS = Customer-managed keys (more control, small cost)
    encryption_type = "AES256"
  }

  # tags: Metadata for organization and cost tracking
  # merge() combines two maps into one
  tags = merge(
    var.tags,  # Global tags from variables.tf
    {
      Name = "${var.project_name}-${var.environment}-ecr"
      # Additional specific tags for this resource
    }
  )
}

# -----------------------------------------------------------------------------
# ECR Lifecycle Policy
# -----------------------------------------------------------------------------
# Automatically delete old images to save storage costs
# ECR charges $0.10/GB per month - can add up with many images

resource "aws_ecr_lifecycle_policy" "app" {
  # repository: Which ECR repo this policy applies to
  # Reference syntax: resource_type.local_name.attribute
  repository = aws_ecr_repository.app.name
  # This creates a dependency: lifecycle policy created AFTER repository

  # policy: JSON document defining cleanup rules
  # jsonencode() converts Terraform objects to JSON
  policy = jsonencode({
    rules = [
      {
        # Rule 1: Keep only the last 5 images
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          # tagStatus: untagged or tagged or any
          tagStatus   = "any"
          # countType: imageCountMoreThan keeps N most recent
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = {
          # expire: Delete images matching the selection
          type = "expire"
        }
      }
    ]
  })
  
  # Why this matters:
  # - Every Docker push creates a new image (uses storage)
  # - Old images you don't need cost money
  # - This keeps your 5 most recent, deletes older ones
  # - Saves money without losing important images
}

# -----------------------------------------------------------------------------
# ECR Repository Policy (Optional)
# -----------------------------------------------------------------------------
# Controls WHO can access this repository
# Commented out for now - only you (repository owner) can access

# resource "aws_ecr_repository_policy" "app" {
#   repository = aws_ecr_repository.app.name
#   
#   policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Sid    = "AllowPushPull"
#         Effect = "Allow"
#         Principal = {
#           # AWS = "arn:aws:iam::ACCOUNT_ID:user/other-user"
#           # Would allow another AWS account/user to access
#         }
#         Action = [
#           "ecr:GetDownloadUrlForLayer",
#           "ecr:BatchGetImage",
#           "ecr:BatchCheckLayerAvailability",
#           "ecr:PutImage",
#           "ecr:InitiateLayerUpload",
#           "ecr:UploadLayerPart",
#           "ecr:CompleteLayerUpload"
#         ]
#       }
#     ]
#   })
# }

# =============================================================================
# OUTPUTS
# =============================================================================
# Output values you'll need to reference later

output "ecr_repository_url" {
  description = "URL of the ECR repository - use this to push images"
  value       = aws_ecr_repository.app.repository_url
  # Example output: "123456789012.dkr.ecr.us-east-1.amazonaws.com/news-analytics-dev"
  # You'll use this when running: docker push <this_url>:latest
}

output "ecr_repository_arn" {
  description = "ARN of the ECR repository"
  value       = aws_ecr_repository.app.arn
  # ARN = Amazon Resource Name (unique identifier for any AWS resource)
  # Format: arn:aws:ecr:region:account:repository/name
}
