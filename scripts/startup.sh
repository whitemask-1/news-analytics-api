#!/bin/bash
set -e

# ==============================================================================
# STARTUP SCRIPT - Resume development work
# ==============================================================================
# This script rebuilds the infrastructure for a new development session
#
# Usage: ./scripts/startup.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_ROOT/infra"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  News Analytics API - Development Startup                     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Change to infrastructure directory
cd "$INFRA_DIR"

# ==============================================================================
# Preflight checks
# ==============================================================================
echo -e "${YELLOW}Running preflight checks...${NC}"
echo ""

# Check AWS credentials
if ! aws sts get-caller-identity &>/dev/null; then
    echo -e "${RED}✗ AWS credentials not configured${NC}"
    echo "  Run: aws configure"
    exit 1
fi
echo -e "${GREEN}✓ AWS credentials valid${NC}"

# Check Terraform
if ! command -v terraform &>/dev/null; then
    echo -e "${RED}✗ Terraform not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Terraform installed${NC}"

# Check Docker
if ! command -v docker &>/dev/null; then
    echo -e "${RED}✗ Docker not installed${NC}"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo -e "${RED}✗ Docker daemon not running${NC}"
    echo "  Start Docker Desktop or run: sudo systemctl start docker"
    exit 1
fi
echo -e "${GREEN}✓ Docker running${NC}"

echo ""

# ==============================================================================
# Show estimated time and cost
# ==============================================================================
echo -e "${BLUE}Deployment details:${NC}"
echo "  • Estimated time: 5-10 minutes"
echo "  • Resources to create:"
echo "    - Lambda functions (2)"
echo "    - API Gateway"
echo "    - SQS queues (2)"
echo "    - CloudWatch log groups"
echo "    - Docker image rebuild and push"
echo ""
echo -e "${YELLOW}Existing resources (preserved from last session):${NC}"
echo "  • Secrets Manager: 3 secrets"
echo "  • ECR repository"
echo "  • S3 buckets (empty)"
echo "  • Athena tables"
echo ""

read -p "Continue with startup? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo -e "${RED}Startup cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Starting deployment...${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# ==============================================================================
# Initialize Terraform
# ==============================================================================
echo -e "${YELLOW}[1/3] Initializing Terraform...${NC}"
terraform init -upgrade
echo -e "${GREEN}  ✓ Terraform initialized${NC}"
echo ""

# ==============================================================================
# Plan and apply
# ==============================================================================
echo -e "${YELLOW}[2/3] Reviewing deployment plan...${NC}"
echo ""
terraform plan
echo ""

read -p "Apply this plan? (yes/no): " apply_confirm
if [[ "$apply_confirm" != "yes" ]]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}[3/3] Deploying infrastructure...${NC}"
echo -e "${YELLOW}This will take 5-10 minutes (Docker image rebuild)...${NC}"
echo ""

terraform apply -auto-approve

echo ""
echo -e "${GREEN}  ✓ Infrastructure deployed${NC}"
echo ""

# ==============================================================================
# Save outputs for easy access
# ==============================================================================
echo -e "${YELLOW}Saving deployment outputs...${NC}"

# Export endpoints to shell script
cat > "$PROJECT_ROOT/dev-env.sh" <<EOF
#!/bin/bash
# Development environment variables
# Source this file: source dev-env.sh

export API_URL="$(terraform output -raw api_gateway_url)"
export API_HEALTH_CHECK="\${API_URL}/health"
export API_INGEST="\${API_URL}/api/v1/ingest"
export API_ANALYTICS="\${API_URL}/api/v1/analytics/search"

export SQS_QUEUE_URL="$(terraform output -raw sqs_queue_url)"
export SQS_DLQ_URL="$(terraform output -raw sqs_dlq_url)"

export S3_BUCKET_RAW="$(terraform output -raw s3_bucket_raw_name)"
export S3_BUCKET_NORMALIZED="$(terraform output -raw s3_bucket_normalized_name)"
export S3_BUCKET_ATHENA="$(terraform output -raw s3_bucket_athena_name)"

echo "Environment variables loaded!"
echo "API URL: \$API_URL"
EOF

chmod +x "$PROJECT_ROOT/dev-env.sh"

echo -e "${GREEN}  ✓ Environment variables saved to dev-env.sh${NC}"
echo ""

# ==============================================================================
# Test deployment
# ==============================================================================
echo -e "${YELLOW}Testing deployment...${NC}"

API_URL=$(terraform output -raw api_gateway_url)
HEALTH_URL="${API_URL}/health"

echo "  Waiting 5 seconds for Lambda to be ready..."
sleep 5

echo "  Testing health endpoint..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL")

if [[ "$HTTP_CODE" == "200" ]]; then
    echo -e "${GREEN}  ✓ Health check passed (HTTP $HTTP_CODE)${NC}"
    HEALTH_RESPONSE=$(curl -s "$HEALTH_URL")
    echo "  Response: $HEALTH_RESPONSE"
else
    echo -e "${RED}  ✗ Health check failed (HTTP $HTTP_CODE)${NC}"
    echo "  Check Lambda logs: aws logs tail /aws/lambda/news-analytics-dev-api --follow"
fi

echo ""

# ==============================================================================
# Success summary
# ==============================================================================
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Startup complete!${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}API Endpoints:${NC}"
echo "  Health:     $HEALTH_URL"
echo "  Ingest:     ${API_URL}/api/v1/ingest"
echo "  Analytics:  ${API_URL}/api/v1/analytics/search"
echo ""
echo -e "${GREEN}Quick commands:${NC}"
echo "  # Load environment variables"
echo "  source dev-env.sh"
echo ""
echo "  # Test ingestion"
echo "  curl -X POST \$API_INGEST -H 'Content-Type: application/json' \\"
echo "    -d '{\"query\":\"test\",\"limit\":2,\"language\":\"en\"}'"
echo ""
echo "  # Monitor worker logs"
echo "  aws logs tail /aws/lambda/news-analytics-dev-worker --follow"
echo ""
echo "  # Check S3 data"
echo "  aws s3 ls s3://\$S3_BUCKET_RAW/raw/ --recursive"
echo ""
echo -e "${YELLOW}When done for the day:${NC}"
echo "  ./scripts/shutdown.sh"
echo ""
