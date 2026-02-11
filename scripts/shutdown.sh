#!/bin/bash
set -e

# ==============================================================================
# SHUTDOWN SCRIPT - Clean up AWS resources to minimize costs
# ==============================================================================
# This script destroys expensive resources while keeping secrets intact
# to avoid the 7-day recovery window issue
#
# Cost Impact:
# - Keeps: Secrets Manager ($1.20/month), ECR repo ($0)
# - Destroys: Lambda, API Gateway, SQS, CloudWatch Logs, S3 data
# - Saves: ~$1-2/month (mostly Lambda/S3/CloudWatch)
#
# Usage: ./scripts/shutdown.sh

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
echo -e "${BLUE}║  News Analytics API - Development Shutdown                    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Change to infrastructure directory
cd "$INFRA_DIR"

# ==============================================================================
# Step 1: Confirm shutdown
# ==============================================================================
echo -e "${YELLOW}This will destroy the following resources:${NC}"
echo "  ✓ Lambda functions (API + Worker)"
echo "  ✓ API Gateway"
echo "  ✓ SQS queues"
echo "  ✓ CloudWatch log groups"
echo "  ✓ S3 data (raw + normalized articles)"
echo ""
echo -e "${GREEN}The following will be PRESERVED:${NC}"
echo "  ✓ Secrets Manager secrets (avoid 7-day recovery window)"
echo "  ✓ ECR repository (avoid re-pushing images)"
echo "  ✓ S3 buckets (empty but structure remains)"
echo "  ✓ Athena database/tables"
echo ""
echo -e "${YELLOW}Estimated cost while shut down: ~$1.20/month (secrets only)${NC}"
echo ""

read -p "Continue with shutdown? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo -e "${RED}Shutdown cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Starting shutdown sequence...${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# ==============================================================================
# Step 2: Clean up S3 data
# ==============================================================================
echo -e "${YELLOW}[1/6] Cleaning S3 buckets...${NC}"

# Get bucket names from Terraform
RAW_BUCKET=$(terraform output -raw s3_bucket_raw_name 2>/dev/null || echo "")
NORMALIZED_BUCKET=$(terraform output -raw s3_bucket_normalized_name 2>/dev/null || echo "")
ATHENA_BUCKET=$(terraform output -raw s3_bucket_athena_name 2>/dev/null || echo "")

if [[ -n "$RAW_BUCKET" ]]; then
    echo "  Emptying $RAW_BUCKET..."
    aws s3 rm "s3://$RAW_BUCKET" --recursive --quiet 2>/dev/null || true
fi

if [[ -n "$NORMALIZED_BUCKET" ]]; then
    echo "  Emptying $NORMALIZED_BUCKET..."
    aws s3 rm "s3://$NORMALIZED_BUCKET" --recursive --quiet 2>/dev/null || true
fi

if [[ -n "$ATHENA_BUCKET" ]]; then
    echo "  Emptying $ATHENA_BUCKET..."
    aws s3 rm "s3://$ATHENA_BUCKET" --recursive --quiet 2>/dev/null || true
fi

echo -e "${GREEN}  ✓ S3 data cleaned${NC}"
echo ""

# ==============================================================================
# Step 3: Purge SQS queues
# ==============================================================================
echo -e "${YELLOW}[2/6] Purging SQS queues...${NC}"

QUEUE_URL=$(terraform output -raw sqs_queue_url 2>/dev/null || echo "")
DLQ_URL=$(terraform output -raw sqs_dlq_url 2>/dev/null || echo "")

if [[ -n "$QUEUE_URL" ]]; then
    echo "  Purging main queue..."
    aws sqs purge-queue --queue-url "$QUEUE_URL" 2>/dev/null || true
fi

if [[ -n "$DLQ_URL" ]]; then
    echo "  Purging dead letter queue..."
    aws sqs purge-queue --queue-url "$DLQ_URL" 2>/dev/null || true
fi

echo -e "${GREEN}  ✓ SQS queues purged${NC}"
echo ""

# ==============================================================================
# Step 4: Delete CloudWatch log groups (optional - saves pennies)
# ==============================================================================
echo -e "${YELLOW}[3/6] Deleting CloudWatch logs...${NC}"

aws logs delete-log-group --log-group-name /aws/lambda/news-analytics-dev-api 2>/dev/null || true
aws logs delete-log-group --log-group-name /aws/lambda/news-analytics-dev-worker 2>/dev/null || true

echo -e "${GREEN}  ✓ CloudWatch logs deleted${NC}"
echo ""

# ==============================================================================
# Step 5: Destroy Lambda and expensive resources (preserve secrets)
# ==============================================================================
echo -e "${YELLOW}[4/6] Destroying Lambda functions and API Gateway...${NC}"

# Destroy specific resources, excluding secrets and ECR
terraform destroy -auto-approve \
  -target=aws_lambda_function.api_handler \
  -target=aws_lambda_function.worker \
  -target=aws_lambda_event_source_mapping.sqs_trigger \
  -target=aws_apigatewayv2_api.http_api \
  -target=aws_apigatewayv2_stage.default \
  -target=aws_apigatewayv2_integration.lambda \
  -target=aws_apigatewayv2_route.health \
  -target=aws_apigatewayv2_route.ingest \
  -target=aws_apigatewayv2_route.analytics_search \
  -target=aws_lambda_permission.api_gateway \
  -target=aws_sqs_queue.ingest_queue \
  -target=aws_sqs_queue.ingest_dlq \
  -target=aws_cloudwatch_metric_alarm.dlq_alarm \
  -target=aws_cloudwatch_log_group.api_lambda_logs \
  -target=aws_cloudwatch_log_group.worker_lambda_logs \
  -target=null_resource.docker_build_push

echo -e "${GREEN}  ✓ Lambda and API Gateway destroyed${NC}"
echo ""

# ==============================================================================
# Step 6: Summary
# ==============================================================================
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Shutdown complete!${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}Resources preserved:${NC}"
echo "  • Secrets Manager: 3 secrets ($1.20/month)"
echo "  • ECR repository: 1 repo ($0/month)"
echo "  • S3 buckets: empty but exist ($0/month)"
echo "  • Athena database/tables: metadata only ($0/month)"
echo "  • IAM roles: $0/month"
echo ""
echo -e "${YELLOW}Estimated monthly cost while shut down: ~$1.20${NC}"
echo ""
echo -e "${BLUE}To restart development:${NC}"
echo "  1. cd infra"
echo "  2. terraform apply"
echo "  3. Wait 5-10 minutes for Docker image rebuild"
echo ""
echo -e "${BLUE}Or use the startup script:${NC}"
echo "  ./scripts/startup.sh"
echo ""
