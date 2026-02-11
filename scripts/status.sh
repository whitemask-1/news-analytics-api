#!/bin/bash

# ==============================================================================
# STATUS SCRIPT - Check current deployment status and costs
# ==============================================================================
# Usage: ./scripts/status.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_ROOT/infra"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}News Analytics API - Status Report${NC}"
echo "========================================"
echo ""

cd "$INFRA_DIR"

# Check if infrastructure is deployed
if ! terraform state list &>/dev/null; then
    echo -e "${RED}No infrastructure found${NC}"
    echo "Run: ./scripts/startup.sh"
    exit 0
fi

# Lambda functions
echo -e "${BLUE}Lambda Functions:${NC}"
API_LAMBDA=$(terraform state list 2>/dev/null | grep -c "aws_lambda_function.api_handler" || echo "0")
WORKER_LAMBDA=$(terraform state list 2>/dev/null | grep -c "aws_lambda_function.worker" || echo "0")

if [[ "$API_LAMBDA" == "1" ]]; then
    echo -e "  ${GREEN}✓ API Lambda deployed${NC}"
else
    echo -e "  ${YELLOW}○ API Lambda not deployed${NC}"
fi

if [[ "$WORKER_LAMBDA" == "1" ]]; then
    echo -e "  ${GREEN}✓ Worker Lambda deployed${NC}"
else
    echo -e "  ${YELLOW}○ Worker Lambda not deployed${NC}"
fi

# API Gateway
API_GW=$(terraform state list 2>/dev/null | grep -c "aws_apigatewayv2_api.http_api" || echo "0")
if [[ "$API_GW" == "1" ]]; then
    echo -e "  ${GREEN}✓ API Gateway deployed${NC}"
    API_URL=$(terraform output -raw api_gateway_url 2>/dev/null || echo "")
    if [[ -n "$API_URL" ]]; then
        echo "    URL: $API_URL"
    fi
else
    echo -e "  ${YELLOW}○ API Gateway not deployed${NC}"
fi

echo ""

# Secrets
echo -e "${BLUE}Secrets Manager:${NC}"
SECRETS=$(terraform state list 2>/dev/null | grep "aws_secretsmanager_secret\." | wc -l)
echo "  Secrets: $SECRETS"
echo "  Cost: \$$(echo "$SECRETS * 0.40" | bc)/month"
echo ""

# S3 Buckets
echo -e "${BLUE}S3 Storage:${NC}"
RAW_BUCKET=$(terraform output -raw s3_bucket_raw_name 2>/dev/null || echo "")
NORMALIZED_BUCKET=$(terraform output -raw s3_bucket_normalized_name 2>/dev/null || echo "")

if [[ -n "$RAW_BUCKET" ]]; then
    RAW_SIZE=$(aws s3 ls "s3://$RAW_BUCKET" --recursive --summarize 2>/dev/null | grep "Total Size" | awk '{print $3}')
    RAW_SIZE_MB=$(echo "scale=2; ${RAW_SIZE:-0} / 1024 / 1024" | bc)
    echo "  Raw: ${RAW_SIZE_MB} MB"
fi

if [[ -n "$NORMALIZED_BUCKET" ]]; then
    NORM_SIZE=$(aws s3 ls "s3://$NORMALIZED_BUCKET" --recursive --summarize 2>/dev/null | grep "Total Size" | awk '{print $3}')
    NORM_SIZE_MB=$(echo "scale=2; ${NORM_SIZE:-0} / 1024 / 1024" | bc)
    echo "  Normalized: ${NORM_SIZE_MB} MB"
fi

echo ""

# SQS Queues
echo -e "${BLUE}SQS Queues:${NC}"
QUEUE_URL=$(terraform output -raw sqs_queue_url 2>/dev/null || echo "")
DLQ_URL=$(terraform output -raw sqs_dlq_url 2>/dev/null || echo "")

if [[ -n "$QUEUE_URL" ]]; then
    QUEUE_MSGS=$(aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names ApproximateNumberOfMessages 2>/dev/null | jq -r '.Attributes.ApproximateNumberOfMessages')
    echo "  Main queue: ${QUEUE_MSGS:-0} messages"
fi

if [[ -n "$DLQ_URL" ]]; then
    DLQ_MSGS=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names ApproximateNumberOfMessages 2>/dev/null | jq -r '.Attributes.ApproximateNumberOfMessages')
    echo "  DLQ: ${DLQ_MSGS:-0} messages"
    if [[ "${DLQ_MSGS:-0}" -gt "0" ]]; then
        echo -e "  ${RED}⚠ Failed messages in DLQ!${NC}"
    fi
fi

echo ""

# Lambda invocations today
echo -e "${BLUE}Usage Today:${NC}"
TODAY_START=$(date -u +%Y-%m-%dT00:00:00)
NOW=$(date -u +%Y-%m-%dT%H:%M:%S)

API_INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=news-analytics-dev-api \
  --start-time "$TODAY_START" \
  --end-time "$NOW" \
  --period 86400 \
  --statistics Sum \
  --query 'Datapoints[0].Sum' \
  --output text 2>/dev/null || echo "0")

WORKER_INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=news-analytics-dev-worker \
  --start-time "$TODAY_START" \
  --end-time "$NOW" \
  --period 86400 \
  --statistics Sum \
  --query 'Datapoints[0].Sum' \
  --output text 2>/dev/null || echo "0")

echo "  API Lambda: ${API_INVOCATIONS:-0} invocations"
echo "  Worker Lambda: ${WORKER_INVOCATIONS:-0} invocations"

echo ""

# Estimated monthly cost
echo -e "${BLUE}Estimated Costs:${NC}"

# Calculate Lambda cost (very rough estimate)
TOTAL_INVOCATIONS=$(echo "${API_INVOCATIONS:-0} + ${WORKER_INVOCATIONS:-0}" | bc)
LAMBDA_COST_PER_MILLION=0.20
ESTIMATED_MONTHLY_INVOCATIONS=$(echo "$TOTAL_INVOCATIONS * 30" | bc)
LAMBDA_MONTHLY_COST=$(echo "scale=2; $ESTIMATED_MONTHLY_INVOCATIONS * $LAMBDA_COST_PER_MILLION / 1000000" | bc)

# S3 cost
TOTAL_SIZE_GB=$(echo "scale=3; (${RAW_SIZE:-0} + ${NORM_SIZE:-0}) / 1024 / 1024 / 1024" | bc)
S3_MONTHLY_COST=$(echo "scale=2; $TOTAL_SIZE_GB * 0.023" | bc)

# Secrets cost
SECRETS_COST=$(echo "scale=2; $SECRETS * 0.40" | bc)

# Total
TOTAL_COST=$(echo "scale=2; $LAMBDA_MONTHLY_COST + $S3_MONTHLY_COST + $SECRETS_COST + 0.50" | bc)

echo "  Lambda: ~\$${LAMBDA_MONTHLY_COST}/month"
echo "  S3: ~\$${S3_MONTHLY_COST}/month"
echo "  Secrets: \$${SECRETS_COST}/month"
echo "  Other (CloudWatch, etc): ~\$0.50/month"
echo "  ─────────────────────"
echo "  Total: ~\$${TOTAL_COST}/month"

echo ""

# EventBridge status
EVENTBRIDGE=$(terraform state list 2>/dev/null | grep -c "aws_cloudwatch_event_rule" || echo "0")
if [[ "$EVENTBRIDGE" == "0" ]]; then
    echo -e "${GREEN}✓ EventBridge disabled (manual ingestion only)${NC}"
else
    echo -e "${YELLOW}⚠ EventBridge ENABLED - automatic ingestion active${NC}"
fi

echo ""
echo "Quick commands:"
echo "  ./scripts/shutdown.sh    - Shut down for the day"
echo "  ./scripts/startup.sh     - Resume development"
echo ""
