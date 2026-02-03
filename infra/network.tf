# =============================================================================
# VPC (Virtual Private Cloud)
# =============================================================================
# VPC = Your own isolated network in AWS
# Think of it like your own private data center with complete control over:
# - IP address ranges
# - Subnets (network segments)
# - Route tables (traffic rules)
# - Gateways (connections to internet)

resource "aws_vpc" "main" {
  # cidr_block: The IP address range for your VPC
  # CIDR notation: 10.0.0.0/16 means:
  # - All IPs from 10.0.0.0 to 10.0.255.255 (65,536 addresses)
  # - /16 means first 16 bits are fixed (10.0), last 16 bits are variable
  cidr_block = "10.0.0.0/16"
  
  # enable_dns_hostnames: Assigns DNS names to instances
  # true = instances get names like ec2-xx-xx-xx-xx.compute.amazonaws.com
  # Needed for ECS to resolve container names
  enable_dns_hostnames = true
  
  # enable_dns_support: Enables DNS resolution within VPC
  # true = instances can resolve domain names (like api.newsapi.org)
  enable_dns_support = true

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-vpc"
    }
  )
}

# =============================================================================
# SUBNETS
# =============================================================================
# Subnets divide your VPC into smaller networks
# Each subnet exists in ONE availability zone
# Best practice: create subnets in multiple AZs for high availability

# -----------------------------------------------------------------------------
# Public Subnets
# -----------------------------------------------------------------------------
# "Public" = has route to Internet Gateway = can access internet directly
# Your containers will live here (when enable_nat_gateway = false)

resource "aws_subnet" "public" {
  # count: Creates multiple resources (one per availability zone)
  # length() returns the number of items in the list
  count = length(var.availability_zones)
  # If availability_zones = ["us-east-1a", "us-east-1b"]
  # Then count = 2, creating 2 subnets

  vpc_id = aws_vpc.main.id
  # References the VPC we created above
  # Creates dependency: VPC must exist before subnets

  # cidrsubnet() function: Divides VPC CIDR into smaller subnets
  # Syntax: cidrsubnet(vpc_cidr, newbits, netnum)
  # vpc_cidr: 10.0.0.0/16
  # newbits: 8 (makes it /24 instead of /16)
  # netnum: count.index (0, 1, 2, etc.)
  # Result:
  #   Subnet 0: 10.0.0.0/24 (10.0.0.0 to 10.0.0.255)
  #   Subnet 1: 10.0.1.0/24 (10.0.1.0 to 10.0.1.255)
  cidr_block = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)

  # availability_zone: Which AZ this subnet lives in
  # count.index: 0 for first subnet, 1 for second, etc.
  availability_zone = var.availability_zones[count.index]

  # map_public_ip_on_launch: Auto-assign public IPs to instances
  # true = containers get public IPs (can be reached from internet)
  # Required when not using NAT Gateway
  map_public_ip_on_launch = true

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-public-${var.availability_zones[count.index]}"
      Type = "Public"
    }
  )
}

# -----------------------------------------------------------------------------
# Private Subnets (Optional - for NAT Gateway setup)
# -----------------------------------------------------------------------------
# "Private" = no direct internet access, goes through NAT Gateway
# More secure but costs ~$32/month for NAT Gateway

resource "aws_subnet" "private" {
  # Only create if NAT Gateway is enabled
  count = var.enable_nat_gateway ? length(var.availability_zones) : 0
  # Ternary operator: condition ? true_value : false_value
  # If enable_nat_gateway = false, count = 0 (no private subnets created)

  vpc_id            = aws_vpc.main.id
  # Start private subnets at 10.0.100.x to avoid overlap with public
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 100)
  availability_zone = var.availability_zones[count.index]

  # Private subnets DON'T auto-assign public IPs
  map_public_ip_on_launch = false

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-private-${var.availability_zones[count.index]}"
      Type = "Private"
    }
  )
}

# =============================================================================
# INTERNET GATEWAY
# =============================================================================
# Gateway that connects your VPC to the internet
# Required for any internet access (inbound or outbound)

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-igw"
    }
  )
}

# =============================================================================
# ROUTE TABLES
# =============================================================================
# Route tables control where network traffic goes
# Think of them like a GPS for network packets

# -----------------------------------------------------------------------------
# Public Route Table
# -----------------------------------------------------------------------------
# Routes for public subnets (direct internet access)

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-public-rt"
    }
  )
}

# Route: Send all internet traffic (0.0.0.0/0) to Internet Gateway
resource "aws_route" "public_internet_access" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  # 0.0.0.0/0 = all internet addresses
  gateway_id             = aws_internet_gateway.main.id
  # Send to Internet Gateway for direct internet access
}

# Associate public subnets with public route table
resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
  # This connects the route table to the subnets
}

# =============================================================================
# SECURITY GROUPS
# =============================================================================
# Security Groups = Stateful firewalls for your resources
# Control inbound and outbound traffic with allow rules

# -----------------------------------------------------------------------------
# ALB Security Group
# -----------------------------------------------------------------------------
# Controls traffic to the Application Load Balancer
# Load Balancer sits in front of your containers

resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-${var.environment}-alb-"
  # name_prefix: Terraform adds random suffix (handles name conflicts)
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  # Ingress = Inbound rules (who can connect TO this resource)
  ingress {
    description = "Allow HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    # 0.0.0.0/0 = anyone on the internet can access port 80
    # This is normal for a public API
  }

  ingress {
    description = "Allow HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    # For HTTPS (encrypted traffic)
    # You'd need an SSL certificate to actually use this
  }

  # Egress = Outbound rules (where can THIS resource connect to)
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    # protocol "-1" = all protocols (TCP, UDP, ICMP, etc.)
    cidr_blocks = ["0.0.0.0/0"]
    # Load balancer can connect anywhere (to reach ECS containers)
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-alb-sg"
    }
  )

  # lifecycle: Special meta-argument for resource behavior
  lifecycle {
    create_before_destroy = true
    # When updating, create new SG before deleting old one
    # Prevents downtime during updates
  }
}

# -----------------------------------------------------------------------------
# ECS Container Security Group
# -----------------------------------------------------------------------------
# Controls traffic to your containers

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${var.project_name}-${var.environment}-ecs-tasks-"
  description = "Security group for ECS tasks"
  vpc_id      = aws_vpc.main.id

  # Ingress: Only allow traffic from Load Balancer
  ingress {
    description     = "Allow traffic from ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    # security_groups instead of cidr_blocks = only from other SG
    # Only the Load Balancer can reach containers directly
    # This is the security layer!
  }

  # Egress: Allow containers to make outbound calls
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    # Containers can call NewsAPI, pull from ECR, etc.
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-ecs-tasks-sg"
    }
  )

  lifecycle {
    create_before_destroy = true
  }
}

# =============================================================================
# APPLICATION LOAD BALANCER (ALB)
# =============================================================================
# Distributes incoming traffic across your containers
# Provides a stable DNS name even when containers restart

resource "aws_lb" "main" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false
  # internal = false means internet-facing (public)
  # internal = true means only accessible from within VPC
  
  load_balancer_type = "application"
  # "application" = Layer 7 (HTTP/HTTPS, path-based routing)
  # "network" = Layer 4 (TCP/UDP, ultra high performance)
  
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  # [*].id = splat operator, gets all IDs from the list
  # ALB must span at least 2 subnets in different AZs

  # enable_deletion_protection: Prevent accidental deletion
  enable_deletion_protection = false
  # Set to true in production!

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-alb"
    }
  )
}

# -----------------------------------------------------------------------------
# Target Group
# -----------------------------------------------------------------------------
# Target Group = Collection of targets (containers) that receive traffic
# Load balancer forwards requests here

resource "aws_lb_target_group" "app" {
  name        = "${var.project_name}-${var.environment}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  # target_type = "ip" for Fargate (containers don't have EC2 instance IDs)
  # ECS will register container IPs here automatically

  # Health check: How ALB knows if container is healthy
  health_check {
    enabled             = true
    healthy_threshold   = 2
    # healthy_threshold = 2: need 2 successful checks to mark healthy
    interval            = 30
    # Check every 30 seconds
    matcher             = "200"
    # HTTP 200 = success
    path                = "/api/v1/health"
    # Your FastAPI health endpoint
    protocol            = "HTTP"
    timeout             = 5
    # Wait 5 seconds for response
    unhealthy_threshold = 2
    # 2 failed checks = mark unhealthy (stop sending traffic)
  }

  # deregistration_delay: Wait time before removing unhealthy target
  deregistration_delay = 30
  # Give container 30 seconds to finish current requests before removal

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-tg"
    }
  )
}

# -----------------------------------------------------------------------------
# Listener
# -----------------------------------------------------------------------------
# Listener = Checks for connection requests on a port
# When request comes in, forwards to target group

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # default_action: What to do with requests
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
    # Forward all HTTP traffic to our target group (containers)
  }

  tags = var.tags
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = aws_subnet.public[*].id
}

output "alb_dns_name" {
  description = "DNS name of the load balancer - use this to access your API"
  value       = aws_lb.main.dns_name
  # Example: news-analytics-dev-alb-123456789.us-east-1.elb.amazonaws.com
  # Your API will be available at: http://<this_dns>/api/v1/health
}

output "alb_security_group_id" {
  description = "Security group ID for ALB"
  value       = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  description = "Security group ID for ECS tasks"
  value       = aws_security_group.ecs_tasks.id
}

output "target_group_arn" {
  description = "ARN of the target group"
  value       = aws_lb_target_group.app.arn
}
