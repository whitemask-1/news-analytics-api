# =============================================================================
# ECS (Elastic Container Service)
# =============================================================================
# ECS is AWS's container orchestration service
# Think of it like a manager that:
# - Keeps your containers running
# - Restarts them if they crash
# - Scales them up/down
# - Registers them with the load balancer

# =============================================================================
# ECS CLUSTER
# =============================================================================
# A cluster is a logical grouping of tasks/services
# It's like a namespace - doesn't cost anything by itself

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}-cluster"

  # Container Insights: Detailed monitoring (CPU, memory, network)
  # Costs extra but helpful for debugging
  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-cluster"
    }
  )
}

# =============================================================================
# ECS TASK DEFINITION
# =============================================================================
# Task Definition = Blueprint for running your container
# Like docker-compose.yml but for AWS
# Defines: image, CPU, memory, ports, environment variables, etc.

resource "aws_ecs_task_definition" "app" {
  family = "${var.project_name}-${var.environment}"
  # family: Name for this task definition
  # Each time you update, a new revision is created (like versions)

  # Network mode for Fargate
  network_mode = "awsvpc"
  # awsvpc: Each task gets its own network interface (ENI)
  # Required for Fargate

  # Fargate: Serverless compute (no EC2 instances to manage)
  requires_compatibilities = ["FARGATE"]

  # CPU and Memory at task level (not container level)
  # Must use specific Fargate combinations
  cpu    = var.container_cpu
  memory = var.container_memory

  # IAM roles we created in iam.tf
  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  # Used BY ECS to pull image, write logs

  task_role_arn = aws_iam_role.ecs_task_role.arn
  # Used BY your application to access AWS services

  # Container definitions: JSON array of containers
  # We only have one container, but you could have multiple (sidecar pattern)
  container_definitions = jsonencode([
    {
      name  = "${var.project_name}-${var.environment}"
      image = "${aws_ecr_repository.app.repository_url}:latest"
      # Image from ECR - pulls the :latest tag
      # In production, use specific version tags like :v1.2.3

      # essential: If this container stops, stop the entire task
      essential = true

      # Port mappings: Container port to host port
      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
          # With awsvpc, containerPort = hostPort always
        }
      ]

      # Environment variables: Plain text key-value pairs
      # Visible in ECS console - don't put secrets here!
      environment = [
        {
          name  = "LOG_LEVEL"
          value = var.log_level
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        }
      ]

      # Secrets: Pull from Secrets Manager or SSM Parameter Store
      # These are encrypted and not visible in console
      # Commented out - we'll add this when we create secrets.tf
      # secrets = [
      #   {
      #     name      = "NEWSAPI_KEY"
      #     valueFrom = aws_secretsmanager_secret.newsapi_key.arn
      #   }
      # ]

      # CloudWatch Logs configuration
      logConfiguration = {
        logDriver = "awslogs"
        # awslogs: Send logs to CloudWatch

        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
          # Logs will appear at: /ecs/news-analytics-dev/ecs/container-name/task-id
        }
      }

      # Health check: How ECS knows if container is healthy
      # Different from ALB health check!
      healthCheck = {
        command = [
          "CMD-SHELL",
          "curl -f http://localhost:${var.container_port}/api/v1/health || exit 1"
        ]
        # Runs this command inside the container
        # exit 0 = healthy, exit 1 = unhealthy

        interval = 30
        # Check every 30 seconds
        timeout = 5
        # Wait 5 seconds for response
        retries = 3
        # 3 failures = unhealthy
        startPeriod = 60
        # Grace period: don't mark unhealthy during first 60 seconds
        # Gives app time to start up
      }
    }
  ])

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-task"
    }
  )
}

# =============================================================================
# ECS SERVICE
# =============================================================================
# Service = Keeps desired number of tasks running
# Handles self-healing, load balancer integration, deployments

resource "aws_ecs_service" "app" {
  name            = "${var.project_name}-${var.environment}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn

  # Desired count: How many tasks to run
  desired_count = var.desired_count
  # ECS constantly monitors and maintains this count

  # Launch type
  launch_type = "FARGATE"
  # FARGATE = serverless (AWS manages infrastructure)
  # EC2 = you manage EC2 instances

  # Platform version
  platform_version = "LATEST"
  # Fargate platform version (usually leave as LATEST)

  # Networking configuration
  network_configuration {
    # Subnets: Where to launch tasks
    subnets = aws_subnet.public[*].id
    # Uses public subnets (or private if enable_nat_gateway = true)

    # Security groups: Firewall rules
    security_groups = [aws_security_group.ecs_tasks.id]
    # Only allows traffic from ALB

    # Assign public IP
    assign_public_ip = true
    # true = tasks can reach internet directly (for API calls)
    # Set to false if using private subnets with NAT Gateway
  }

  # Load balancer integration
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    # Register tasks with this target group

    container_name = "${var.project_name}-${var.environment}"
    # Must match container name in task definition

    container_port = var.container_port
    # Which container port to send traffic to
  }

  # Deployment configuration
  # These are top-level attributes, not a nested block
  deployment_maximum_percent         = 200
  # Can go up to 200% during deployment (2x desired_count)
  deployment_minimum_healthy_percent = 100
  # Must keep at least 100% healthy during deployment
  
  # Deployment circuit breaker is a block
  deployment_circuit_breaker {
    enable   = true
    rollback = true
    # If deployment fails (tasks keep crashing), automatically rollback
  }

  # Wait for load balancer to be ready before considering deployment successful
  # ECS will wait for tasks to pass ALB health checks
  health_check_grace_period_seconds = 60
  # Don't fail deployment if health checks fail in first 60 seconds

  # Ignore changes to desired_count
  # Allows auto-scaling to modify desired_count without Terraform reverting it
  lifecycle {
    ignore_changes = [desired_count]
  }

  # Dependencies: Ensure listener exists before service
  # Service tries to register with target group, which needs listener
  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy_attachment.ecs_task_execution_role_policy
  ]

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-service"
    }
  )
}

# =============================================================================
# AUTO SCALING (OPTIONAL)
# =============================================================================
# Automatically adjust desired_count based on metrics (CPU, memory, requests)

# Auto Scaling Target: What to scale
resource "aws_appautoscaling_target" "ecs" {
  max_capacity = 4
  # Maximum tasks to scale up to
  min_capacity = 1
  # Minimum tasks to scale down to
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Auto Scaling Policy: When to scale
resource "aws_appautoscaling_policy" "ecs_cpu" {
  name               = "${var.project_name}-${var.environment}-cpu-autoscaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  # Target Tracking: Maintain target value
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
      # Scale based on average CPU across all tasks
    }

    target_value = 70.0
    # Try to keep CPU at 70%
    # Above 70% → scale up (add tasks)
    # Below 70% → scale down (remove tasks)

    scale_in_cooldown = 300
    # Wait 5 minutes after scaling down before scaling down again
    scale_out_cooldown = 60
    # Wait 1 minute after scaling up before scaling up again
  }
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "ecs_cluster_id" {
  description = "ID of the ECS cluster"
  value       = aws_ecs_cluster.main.id
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.app.name
}

output "ecs_task_definition_arn" {
  description = "ARN of the task definition"
  value       = aws_ecs_task_definition.app.arn
}

output "ecs_task_definition_family" {
  description = "Family of the task definition"
  value       = aws_ecs_task_definition.app.family
}
